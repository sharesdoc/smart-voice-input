"""文本注入 (FR-10)。

- 写入：剪贴板 + ⌘V 粘贴（默认，兼容性好），注入后恢复原剪贴板；或键盘直输 Unicode；
- 全部 macOS 事件通过 Quartz CGEvent 实现，懒加载。

真实系统调用在 macOS 上才可用；非 macOS 环境构造 MacInjector 会抛 RuntimeError。
"""

from __future__ import annotations

import platform
import time
from typing import Protocol

# 剪贴板粘贴时序（秒）。⌘V 是异步的：恢复旧剪贴板必须等目标 App 真正消费完粘贴，
# 否则会粘出用户的旧剪贴板内容(bug)。0.05 太短，加长更稳。
_CLIPBOARD_WRITE_SETTLE = 0.02   # 写入剪贴板后、发 ⌘V 前的微等待(让写入落定)
_PASTE_CONSUME_SETTLE = 0.18     # 发 ⌘V 后、恢复旧剪贴板前的等待(让粘贴被消费)

def _clip(text: str, n: int = 80) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + "…"


def _oplog(fmt: str, *args) -> None:
    """记录注入器底层操作(注入/回删)，作为"软件实际做了什么"的地面真相日志。"""
    from .logsetup import get_logger

    get_logger().info(fmt, *args)


def _has_accessibility_trust() -> bool:
    """当前进程是否已获 macOS 辅助功能信任。

    CGEvent 模拟按键依赖该权限；未授权时系统会静默丢弃按键事件，表现为日志看似
    已注入但目标输入框没有文字。无法检查时不阻断，交由实际系统调用处理。
    """
    try:
        import ApplicationServices  # 懒加载

        return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        return True


class Injector(Protocol):
    """注入器接口，便于在 app 层替换/测试。"""

    def type_text(self, text: str) -> None: ...


class MacInjector:
    """基于 Quartz/AppKit 的 macOS 注入器（运行时才加载依赖）。"""

    def __init__(self, method: str = "paste") -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacInjector 仅支持 macOS")
        # 注入方式 (general.inject_method)：paste=剪贴板⌘V(默认,兼容好) | keystroke=直接键入Unicode(不动剪贴板)
        self.method = method if method in ("paste", "keystroke") else "paste"

    # ---- 写入 ----

    def type_text(self, text: str, *, restore_clipboard: bool = True) -> None:
        """写入文本到当前输入框 (FR-10)。按 method 选择粘贴或键盘直输。"""
        if not text:
            return
        if not _has_accessibility_trust():
            _oplog("[OP] 注入失败：当前进程未获 macOS 辅助功能权限，系统会拒绝模拟按键。"
                   "请在 系统设置→隐私与安全性→辅助功能 授权当前启动项后重启。")
            raise RuntimeError("缺少 macOS 辅助功能权限，无法模拟按键注入")
        _oplog("[OP] 注入(%s) %d字: %r", self.method, len(text), _clip(text))
        if self.method == "keystroke":
            self._type_keystroke(text)
        else:
            self._type_paste(text, restore_clipboard=restore_clipboard)

    def _type_paste(self, text: str, *, restore_clipboard: bool = True) -> None:
        """通过剪贴板粘贴写入文本，随后恢复原剪贴板内容。

        关键时序：⌘V 异步，必须等目标 App 真正消费完粘贴再恢复旧剪贴板，
        否则会粘出用户旧剪贴板内容。恢复前用 changeCount 守卫，避免覆盖用户
        在此期间新复制的内容。
        """
        from AppKit import NSPasteboard, NSStringPboardType  # 懒加载

        pb = NSPasteboard.generalPasteboard()
        saved = pb.stringForType_(NSStringPboardType) if restore_clipboard else None

        pb.clearContents()
        pb.setString_forType_(text, NSStringPboardType)
        our_change = pb.changeCount()        # 记录我们写入后的剪贴板版本号
        time.sleep(_CLIPBOARD_WRITE_SETTLE)  # 让写入落定后再粘贴
        self._key_combo("v", command=True)

        if restore_clipboard:
            # 等粘贴真正被目标 App 消费完，再恢复，避免粘出旧剪贴板
            time.sleep(_PASTE_CONSUME_SETTLE)
            # 仅当剪贴板仍是我们写入的内容(无人改动)才恢复，避免覆盖用户新复制的东西
            if pb.changeCount() == our_change:
                pb.clearContents()
                if saved is not None:
                    pb.setString_forType_(saved, NSStringPboardType)

    def _type_keystroke(self, text: str) -> None:
        """直接键入 Unicode 文本（不经剪贴板），用 CGEventKeyboardSetUnicodeString。

        不污染用户剪贴板；但部分应用对合成键盘事件的兼容性不及粘贴，故非默认。
        """
        import Quartz  # 懒加载

        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(text), text)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    # ---- 底层按键事件 ----

    def _key_combo(self, char: str, *, command: bool = False) -> None:
        import Quartz  # 懒加载

        keymap = {"v": 9, "c": 8, "a": 0}
        keycode = keymap[char]
        flags = Quartz.kCGEventFlagMaskCommand if command else 0
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
            if flags:
                Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def make_injector(method: str = "paste") -> Injector:
    """工厂：当前平台对应的注入器。method=paste|keystroke (general.inject_method)。"""
    return MacInjector(method=method)
