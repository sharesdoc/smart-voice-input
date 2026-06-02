"""双击 Command 触发检测 (FR-03)。

核心是一个纯逻辑的状态机 DoubleTapDetector：喂入按键事件（按下/抬起 +
时间戳 + 是否有其他键参与），它判定是否构成"双击 Command"。

判定规则（避免与 ⌘C/⌘V 等组合键冲突）：
- 一次有效 tap = Command 按下后抬起，且按住期间没有其他键被按下；
- 双击 = 两次有效 tap，且两次 Command 抬起的间隔 < double_tap_ms。

全局监听（GlobalHotkeyListener）用 pynput 实现并懒加载，不影响单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DoubleTapDetector:
    """纯逻辑双击检测器。时间戳单位：秒（float）。"""

    double_tap_ms: int = 300

    _cmd_down: bool = False          # Command 当前是否按下
    _other_key_during: bool = False  # 本次按住期间是否有其他键参与
    _last_tap_time: Optional[float] = None  # 上一次有效 tap 的抬起时刻

    def reset(self) -> None:
        self._cmd_down = False
        self._other_key_during = False
        self._last_tap_time = None

    def on_command_down(self, ts: float) -> None:
        self._cmd_down = True
        self._other_key_during = False

    def on_other_key(self, ts: float) -> None:
        """按住 Command 期间其他键被按下 -> 本次不算 tap（是组合键）。"""
        if self._cmd_down:
            self._other_key_during = True

    def on_command_up(self, ts: float) -> bool:
        """Command 抬起。返回 True 表示触发了双击。"""
        was_clean_tap = self._cmd_down and not self._other_key_during
        self._cmd_down = False
        self._other_key_during = False

        if not was_clean_tap:
            # 组合键的一部分，重置双击计时
            self._last_tap_time = None
            return False

        if (
            self._last_tap_time is not None
            and (ts - self._last_tap_time) * 1000.0 <= self.double_tap_ms
        ):
            self._last_tap_time = None  # 消费掉，避免三击误判
            return True

        self._last_tap_time = ts
        return False


# 已实现的触发方式（trigger）。其余值(如 push_to_talk)暂未实现，会回退为双击 Command。
IMPLEMENTED_TRIGGERS = ("double_command", "custom_hotkey")

# 自定义热键修饰键别名 → 规范名（用于 custom_hotkey 解析与匹配）。
_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "cmd": "cmd", "command": "cmd", "super": "cmd", "win": "cmd",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
}


def parse_combo(spec: str) -> frozenset:
    """把 'ctrl+option+space' 解析为规范键名集合 {'ctrl','alt','space'}。纯函数，可单测。"""
    out = set()
    for part in (spec or "").split("+"):
        p = part.strip().lower()
        if not p:
            continue
        out.add(_MOD_ALIASES.get(p, p))
    return frozenset(out)


class HotkeyMatcher:
    """跟踪当前按下键集合；目标组合首次完整按下时 press() 返回 True（仅一次）。

    纯逻辑、无 pynput 依赖，便于单测。释放任一组合键后重新武装，支持再次触发。
    """

    def __init__(self, combo) -> None:
        self.combo = frozenset(combo)
        self._pressed: set = set()
        self._fired = False

    def press(self, name: str) -> bool:
        if name:
            self._pressed.add(name)
        if self.combo and not self._fired and self.combo <= self._pressed:
            self._fired = True
            return True
        return False

    def release(self, name: str) -> None:
        if name:
            self._pressed.discard(name)
        if not (self.combo <= self._pressed):
            self._fired = False


def _canonical_key(key) -> str:
    """把 pynput 键对象规范化为 parse_combo 同名的键名（用于 custom_hotkey 匹配）。"""
    from pynput import keyboard

    Key = keyboard.Key
    mapping = {
        Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
        Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt",
        Key.cmd: "cmd", Key.cmd_l: "cmd", Key.cmd_r: "cmd",
        Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
        Key.space: "space", Key.enter: "enter", Key.tab: "tab", Key.esc: "esc",
    }
    if key in mapping:
        return mapping[key]
    ch = getattr(key, "char", None)
    if ch:
        return ch.lower()
    return str(key)


class GlobalHotkeyListener:
    """全局监听热键并回调 on_double_tap (FR-03)。

    trigger=double_command（默认）：双击 Command；custom_hotkey：自定义组合键。
    依赖 pynput（懒加载）。需要"输入监控/辅助功能"权限 (FR-13)。
    """

    def __init__(
        self,
        on_double_tap: Callable[[], None],
        double_tap_ms: int = 300,
        on_activity: Optional[Callable[[], None]] = None,
        trigger: str = "double_command",
        custom_hotkey: str = "ctrl+option+space",
    ) -> None:
        self._on_double_tap = on_double_tap
        # on_activity: 任意非触发键活动时回调，用于 FR-17 抢占检测
        self._on_activity = on_activity
        self._detector = DoubleTapDetector(double_tap_ms=double_tap_ms)
        self._trigger = trigger
        self._custom_hotkey = custom_hotkey
        self._listener = None
        self._time = None  # 注入的计时函数

    def start(self) -> None:
        if self._trigger == "custom_hotkey":
            self._start_custom()
        else:
            self._start_double_command()

    def _start_double_command(self) -> None:
        from pynput import keyboard  # 懒加载
        import time

        self._time = time.monotonic
        Key = keyboard.Key

        def is_cmd(key) -> bool:
            return key in (Key.cmd, Key.cmd_l, Key.cmd_r)

        def on_press(key):
            ts = self._time()
            if is_cmd(key):
                self._detector.on_command_down(ts)
            else:
                self._detector.on_other_key(ts)
                if self._on_activity is not None:
                    try:
                        self._on_activity()
                    except Exception:
                        pass

        def on_release(key):
            ts = self._time()
            if is_cmd(key):
                if self._detector.on_command_up(ts):
                    try:
                        self._on_double_tap()
                    except Exception:
                        pass

        self._listener = keyboard.Listener(
            on_press=on_press, on_release=on_release
        )
        self._listener.start()

    def _start_custom(self) -> None:
        """自定义组合键模式：组合完整按下即触发；其余按键视为活动(供抢占)。"""
        from pynput import keyboard  # 懒加载

        matcher = HotkeyMatcher(parse_combo(self._custom_hotkey))

        def on_press(key):
            name = _canonical_key(key)
            if matcher.press(name):
                try:
                    self._on_double_tap()
                except Exception:
                    pass
            elif self._on_activity is not None and name not in matcher.combo:
                try:
                    self._on_activity()
                except Exception:
                    pass

        def on_release(key):
            matcher.release(_canonical_key(key))

        self._listener = keyboard.Listener(
            on_press=on_press, on_release=on_release
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
