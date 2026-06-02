"""原生 Cocoa 系统配置窗口 (PyObjC)。

分类布局：每个参数尽量用下拉框(NSPopUpButton)/开关(NSButton 复选)选择，
仅 URL / API Key 这类必须输入的用文本框。底部 恢复默认 / 取消 / 保存 三按钮。

设计为模态窗口（NSApp.runModalForWindow_）：菜单回调里打开，关闭后返回。
复用 app 的字段读写逻辑（_field_get/_field_set/_restore_defaults/枚举映射）。
"""

from __future__ import annotations

# 布局：('sec',(中,英)) 分组标题；('f', 字段id, 控件类型, 枚举名或None)
# 控件类型：enum(下拉,用_ENUMS) | bool(复选) | pause(下拉预设秒数) |
#           whisper(下拉模型) | ollama(下拉真实模型) | text(输入) | secret(密码输入)
_LAYOUT = [
    ("sec", ("语言", "Language")),
    ("f", "language", "enum", "language"),
    ("sec", ("语音识别（听成文字）", "Speech Recognition")),
    ("f", "asr_engine", "enum", "asr_engine"),
    ("f", "whisper_model", "whisper", None),
    ("f", "mlx_model", "mlx", None),
    ("f", "dashscope_key_source", "enum", "dskey_source"),
    ("f", "dashscope_key", "text", None),
    ("sec", ("听写交互", "Dictation")),
    ("f", "continuous", "bool", None),
    ("f", "pause", "pause", None),
    ("sec", ("文字加工（纠错/润色）", "Post-processing")),
    ("f", "ppmode", "enum", "ppmode"),
    ("sec", ("加工用大模型", "LLM")),
    ("f", "llm_mode", "enum", "llm_mode"),
    ("f", "ollama_model", "ollama", None),
    ("sec", ("在线大模型（可选）", "Online LLM (optional)")),
    ("f", "online_base", "text", None),
    ("f", "online_model", "text", None),
    ("f", "online_key", "secret", None),
    ("sec", ("其他", "Misc")),
    ("f", "autostart", "bool", None),
]

_PAUSE_PRESETS = ["0.3", "0.5", "0.8", "1.0", "1.5", "2.0"]
_WHISPER_PRESETS = ["tiny", "base", "small", "medium"]
_MLX_PRESETS = [
    "mlx-community/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-mlx",
    "mlx-community/whisper-medium-mlx",
    "mlx-community/whisper-small-mlx",
    "mlx-community/whisper-tiny-mlx",
]

# 联动：字段 → 条件列表[(驱动项, 允许值集合)]，全部满足(AND)该字段才可用。
# 链式：后处理(raw不需LLM) → LLM引擎(ollama/online) → 各自参数。
_LLM_ACTIVE = ("ppmode", {"polish", "organize", "translate"})  # raw 不需要 LLM
_DEPS = {
    "whisper_model": [("asr_engine", {"whisper_local"})],
    "mlx_model": [("asr_engine", {"mlx_whisper"})],
    "dashscope_key_source": [("asr_engine", {"dashscope"})],
    "dashscope_key": [("asr_engine", {"dashscope"})],
    "llm_mode": [_LLM_ACTIVE],                                    # 纯转写时禁用LLM引擎
    "ollama_model": [_LLM_ACTIVE, ("llm_mode", {"ollama"})],
    "online_base": [_LLM_ACTIVE, ("llm_mode", {"online"})],
    "online_model": [_LLM_ACTIVE, ("llm_mode", {"online"})],
    "online_key": [_LLM_ACTIVE, ("llm_mode", {"online"})],
}
_DRIVERS = ("asr_engine", "llm_mode", "ppmode")

# 控制器（按钮动作 + 窗口关闭=取消）必须在模块级定义一次，
# 否则每次打开设置都重新定义同名 NSObject 子类会被 PyObjC 拒绝。
_Controller = None


def _set_a11y(ctrl, label: str) -> None:
    """给原生控件设置无障碍标签 (J-P3-02)，便于 VoiceOver 朗读。

    纯薄封装：仅当控件支持 setAccessibilityLabel_ 时设置；任何异常静默忽略
    （无障碍属性失败不应影响设置窗口可用性）。模块级以便单测。
    """
    if not label:
        return
    try:
        ctrl.setAccessibilityLabel_(label)
    except Exception:
        pass


_edit_menu_installed = False


def _ensure_edit_menu():
    """确保 NSApp 有「编辑」菜单(剪切/复制/粘贴/全选)，否则模态窗里 ⌘V 无效。

    菜单栏(accessory)应用默认没有 Edit 菜单 → ⌘C/⌘V/⌘A 等标准快捷键未注册，
    文本框无法粘贴。这些菜单项 action 走响应链，自动作用于当前聚焦的文本框。
    """
    global _edit_menu_installed
    if _edit_menu_installed:
        return
    try:
        from AppKit import NSApplication, NSMenu, NSMenuItem

        app = NSApplication.sharedApplication()
        main = app.mainMenu()
        if main is None:
            main = NSMenu.alloc().init()
            app.setMainMenu_(main)
        edit_menu = NSMenu.alloc().initWithTitle_("编辑")
        for title, sel, key in (
            ("剪切", "cut:", "x"),
            ("复制", "copy:", "c"),
            ("粘贴", "paste:", "v"),
            ("全选", "selectAll:", "a"),
        ):
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
            edit_menu.addItem_(mi)
        holder = NSMenuItem.alloc().init()
        holder.setSubmenu_(edit_menu)
        main.addItem_(holder)
        _edit_menu_installed = True
    except Exception:
        pass


def _get_controller_class():
    global _Controller
    if _Controller is not None:
        return _Controller
    from AppKit import NSApplication
    from Foundation import NSObject

    class _SettingsController(NSObject):
        def save_(self, _s):
            NSApplication.sharedApplication().stopModalWithCode_(1)

        def cancel_(self, _s):
            NSApplication.sharedApplication().stopModalWithCode_(0)

        def restore_(self, _s):
            NSApplication.sharedApplication().stopModalWithCode_(2)

        def windowWillClose_(self, _n):
            NSApplication.sharedApplication().stopModalWithCode_(0)

        def driverChanged_(self, _s):
            fn = getattr(self, "_refresh", None)
            if fn is not None:
                fn()

    _Controller = _SettingsController
    return _Controller


def open_about_window(app) -> None:
    """原生「关于」窗口：软件名/版本/用途/特点/使用说明/发行者。"""
    import platform

    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory,
        NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
        NSBezelStyleRounded, NSButton, NSFont, NSTextField, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect

    from . import __app_name__, __version__

    zh = app.cfg.general.language == "zh"
    if zh:
        body = (
            f"{__app_name__}（语音输入）  v{__version__}\n"
            f"架构：{platform.machine()}\n\n"
            "【用途】\n"
            "macOS 上的 AI 智能语音输入工具：说话即自动在鼠标聚焦的输入框里打字。\n\n"
            "【特点】\n"
            "· 多 ASR 引擎：本地 Whisper / 本地 SenseVoice-Small(极快) / 阿里云 Fun-ASR / 在线\n"
            "· 大模型加工：本地 Ollama 或在线，纠错、加标点、整理\n"
            "· 连续听写：触发一次，按停顿自动分段输入；动态重写、只删自己注入的内容\n"
            "· 中英双语、隐私本地优先\n\n"
            "【使用】\n"
            "双击 Command 进入连续听写 → 说话，停顿约 1 秒自动成段输入 → 再次双击退出。\n"
            "点菜单「系统配置…」调整语言 / 引擎 / 模型等。\n\n"
            "发行者：Z. Johnson"
        )
        title, close_t = "关于", "关闭"
    else:
        body = (
            f"{__app_name__}  v{__version__}\n"
            f"Arch: {platform.machine()}\n\n"
            "[Purpose]\n"
            "An AI voice-input tool for macOS: speak and it types into the focused field.\n\n"
            "[Features]\n"
            "· ASR engines: local Whisper / SenseVoice-Small (fast) / Aliyun Fun-ASR / online\n"
            "· LLM polish: local Ollama or online — fix typos, punctuation, organize\n"
            "· Continuous dictation, dynamic rewrite, deletes only its own text\n"
            "· Chinese/English, privacy local-first\n\n"
            "[Usage]\n"
            "Double-tap Command to start; pause ~1s to auto-segment; double-tap to stop.\n"
            "Open 'System Settings…' to change language / engine / model.\n\n"
            "Publisher: Z. Johnson"
        )
        title, close_t = "About", "Close"

    W, H = 480, 360
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    nsapp.activateIgnoringOtherApps_(True)

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    win.setTitle_(title)
    content = win.contentView()

    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 60, W - 40, H - 80))
    lbl.setStringValue_(body)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(True)              # 可选中复制
    lbl.cell().setWraps_(True)
    lbl.setFont_(NSFont.systemFontOfSize_(12))
    content.addSubview_(lbl)

    ctl = _get_controller_class().alloc().init()
    win.setDelegate_(ctl)
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 120, 16, 100, 30))
    btn.setTitle_(close_t)
    btn.setBezelStyle_(NSBezelStyleRounded)
    btn.setKeyEquivalent_("\r")
    btn.setTarget_(ctl)
    btn.setAction_("cancel:")             # 复用：停止模态
    content.addSubview_(btn)

    win.center()
    win.makeKeyAndOrderFront_(None)
    nsapp.runModalForWindow_(win)
    win.orderOut_(None)
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def open_settings_window(app) -> None:
    """打开原生设置窗口（模态）。保存/恢复默认/取消三种结果。"""
    while True:
        action = _run_dialog(app)
        if action in ("cancel", "save"):
            return
        # restore：已在对话框里重置为默认，循环重开展示默认值
        # （_run_dialog 的 restore 分支已调用 _restore_defaults + 重建菜单）


def _run_dialog(app) -> str:
    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory,
        NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
        NSBezelStyleRounded, NSButton, NSColor, NSFont,
        NSPopUpButton, NSSwitch, NSTextField, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect

    from . import app as appmod
    from .config import get_api_key

    _ensure_edit_menu()  # 装「编辑」菜单，使文本框 ⌘V 粘贴可用

    lang = app.cfg.general.language
    li = 0 if lang == "zh" else 1

    # ---- 尺寸与栅格 ----
    W = 540
    pad = 20
    row_h = 34
    sec_h = 30
    btn_h = 56
    rows_height = sum(sec_h if e[0] == "sec" else row_h for e in _LAYOUT)
    H = pad + rows_height + btn_h + pad
    label_x, label_w = pad, 150
    ctrl_x = label_x + label_w + 12
    ctrl_w = W - ctrl_x - pad

    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    nsapp.activateIgnoringOtherApps_(True)

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    win.setTitle_("系统配置" if lang == "zh" else "System Settings")
    content = win.contentView()

    def mk_label(text, x, y, w, bold=False, secondary=False):
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, 20))
        f.setStringValue_(text)
        f.setBezeled_(False)
        f.setDrawsBackground_(False)
        f.setEditable_(False)
        f.setSelectable_(False)
        if bold:
            f.setFont_(NSFont.boldSystemFontOfSize_(13))
        if secondary:
            f.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(f)
        return f

    reg = {}  # field_id -> (kind, control, enum)
    y = H - pad - 20

    for entry in _LAYOUT:
        if entry[0] == "sec":
            mk_label(entry[1][li], label_x, y, W - 2 * pad, bold=True)
            y -= sec_h
            continue

        _, fid, kind, enum = entry
        label = appmod._LABELS[fid][li]
        mk_label(label, label_x, y - 2, label_w)
        cy = y - 4
        cur = app._field_get(fid)

        if kind == "enum":
            ctrl = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctrl_x, cy, ctrl_w, 26), False)
            titles = [it[1] if li == 0 else it[2] for it in appmod._ENUMS[enum]]
            ctrl.addItemsWithTitles_(titles)
            ctrl.selectItemWithTitle_(appmod._enum_display(enum, cur, lang))
            content.addSubview_(ctrl)
        elif kind == "bool":
            # 用原生开关组件 NSSwitch（非 checkbox）
            ctrl = NSSwitch.alloc().initWithFrame_(NSMakeRect(ctrl_x, cy, 44, 24))
            ctrl.setState_(1 if cur else 0)
            content.addSubview_(ctrl)
        elif kind == "pause":
            ctrl = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctrl_x, cy, ctrl_w, 26), False)
            opts = list(_PAUSE_PRESETS)
            cs = ("%g" % float(cur))
            if cs not in opts:
                opts = [cs] + opts
            ctrl.addItemsWithTitles_([f"{o} 秒" for o in opts])
            ctrl.selectItemWithTitle_(f"{cs} 秒")
            content.addSubview_(ctrl)
        elif kind in ("whisper", "ollama", "mlx"):
            ctrl = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctrl_x, cy, ctrl_w, 26), False)
            if kind == "whisper":
                opts = list(_WHISPER_PRESETS)
            elif kind == "mlx":
                opts = list(_MLX_PRESETS)
            else:
                opts = appmod.list_ollama_models(app.cfg) or []
            if not opts:
                opts = ["(未检测到 / none)"]
            if cur and cur not in opts and not opts[0].startswith("("):
                opts = [cur] + opts
            ctrl.addItemsWithTitles_(opts)
            if cur:
                ctrl.selectItemWithTitle_(cur)
            content.addSubview_(ctrl)
        elif kind in ("text", "secret"):
            # API Key 也用普通 NSTextField：明文显示、支持粘贴(不用 Secure 掩码)
            ctrl = NSTextField.alloc().initWithFrame_(NSMakeRect(ctrl_x, cy, ctrl_w, 24))
            if kind == "secret":
                ctrl.setStringValue_(get_api_key() or "")  # 明文显示已存的 Key
            else:
                ctrl.setStringValue_(str(cur or ""))
            content.addSubview_(ctrl)
        else:
            y -= row_h
            continue

        _set_a11y(ctrl, label)  # 无障碍标签 (J-P3-02)：用字段标签供 VoiceOver 朗读
        reg[fid] = (kind, ctrl, enum)
        y -= row_h

    # ---- 控制器（模块级类，按钮动作 + 关闭=取消）----
    ctl = _get_controller_class().alloc().init()
    win.setDelegate_(ctl)

    # ---- 联动：驱动项(ASR引擎/LLM引擎)变化时启用/禁用相关字段 ----
    def _refresh_enabled():
        cur = {}
        for drv in _DRIVERS:
            if drv in reg:
                _, c, en = reg[drv]
                cur[drv] = appmod._enum_parse(en, c.titleOfSelectedItem())
        for fid, conds in _DEPS.items():
            if fid in reg:
                enabled = all(cur.get(driver) in allowed for driver, allowed in conds)
                reg[fid][1].setEnabled_(enabled)

    for drv in _DRIVERS:
        if drv in reg:
            reg[drv][1].setTarget_(ctl)
            reg[drv][1].setAction_("driverChanged:")
    ctl._refresh = _refresh_enabled
    _refresh_enabled()  # 初始按当前选择置灰/启用

    def mk_btn(title, x, sel, default=False):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, pad, 120, 30))
        b.setTitle_(title)
        b.setBezelStyle_(NSBezelStyleRounded)
        b.setTarget_(ctl)
        b.setAction_(sel)
        if default:
            b.setKeyEquivalent_("\r")
        content.addSubview_(b)
        return b

    save_t = "保存" if lang == "zh" else "Save"
    cancel_t = "取消" if lang == "zh" else "Cancel"
    restore_t = "恢复默认" if lang == "zh" else "Restore Defaults"
    mk_btn(restore_t, pad, "restore:")
    mk_btn(cancel_t, W - pad - 250, "cancel:")
    mk_btn(save_t, W - pad - 120, "save:", default=True)

    win.center()
    win.makeKeyAndOrderFront_(None)
    code = nsapp.runModalForWindow_(win)
    win.orderOut_(None)
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    if code == 1:          # 保存
        _apply(app, reg)
        app._rebuild_menu()
        return "save"
    if code == 2:          # 恢复默认
        app._restore_defaults()
        app._rebuild_menu()
        return "restore"
    return "cancel"


def _apply(app, reg: dict) -> None:
    from . import app as appmod
    from .config import save_config

    for fid, (kind, ctrl, enum) in reg.items():
        if kind == "enum":
            internal = appmod._enum_parse(enum, ctrl.titleOfSelectedItem())
            if internal is not None:
                app._field_set(fid, internal)
        elif kind == "bool":
            val = ctrl.state() == 1
            if fid == "autostart":
                app.apply_autostart(val)   # 真正写/删 LaunchAgent
            else:
                app._field_set(fid, val)
        elif kind == "pause":
            sec = appmod.parse_pause_seconds(ctrl.titleOfSelectedItem())
            if sec is not None:
                app._field_set("pause", sec)
        elif kind in ("whisper", "ollama", "mlx"):
            t = ctrl.titleOfSelectedItem()
            if t and not t.startswith("("):
                app._field_set(fid, t)
        elif kind in ("text", "secret"):
            app._field_set(fid, ctrl.stringValue().strip())

    app._asr = None
    save_config(app.cfg)
