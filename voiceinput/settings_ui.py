"""原生 Cocoa 系统配置窗口 (PyObjC)。

分类布局：每个参数尽量用下拉框(NSPopUpButton)/开关(NSButton 复选)选择，
仅 URL / API Key 这类必须输入的用文本框。底部 恢复默认 / 取消 / 保存 三按钮。

设计为模态窗口（NSApp.runModalForWindow_）：菜单回调里打开，关闭后返回。
复用 app 的字段读写逻辑（_field_get/_field_set/_restore_defaults/枚举映射）。
"""

from __future__ import annotations

from .config import DEFAULT_OLLAMA_MODEL

# 控件类型：enum(下拉) | bool(开关) | pause(预设秒数) |
#           whisper/mlx/ollama(模型下拉) | text(输入) | textarea(多行输入) | secret(密码输入)
# 分类：(中文名, 英文名, [(字段id, 控件类型, 枚举名), ...])。每个分类=侧边栏一项+
# 右侧一个自包含面板。同一分类内的字段功能相关、可有依赖（见 _DEPS）。
_CATEGORIES = [
    ("通用", "General", [
        ("language", "enum", "language"),
        ("autostart", "bool", None),
        ("svr_port", "text", None),
        ("svr_control", "svr", None),
    ]),
    ("噪音过滤", "Noise Filter", [
        ("denoise_enabled", "bool", None),
        ("denoise_attenuation", "text", None),
        ("denoise_dry_wet_mix", "text", None),
        ("silence_threshold", "text", None),
        ("noise_filter", "bool", None),
        ("noise_min_voice_1char", "text", None),
        ("noise_min_voice_2char", "text", None),
        ("noise_min_voice_3char", "text", None),
    ]),
    ("语音识别", "Speech Recognition", [
        ("asr_engine", "enum", "asr_engine"),
        ("force_filter", "text", None),
        ("whisper_model", "whisper", None),
        ("mlx_model", "mlx", None),
        ("dashscope_key_source", "enum", "dskey_source"),
        ("dashscope_key", "text", None),
        ("asr_online_base",  "text",   None),
        ("asr_online_model", "text",   None),
        ("asr_online_key",   "secret", None),
    ]),
    ("听写交互", "Dictation", [
        ("continuous", "bool", None),
        ("pause", "pause", None),
    ]),
    ("智能断句", "Smart Segmentation", [
        ("soft_cap", "text", None),
        ("soft_cap_step", "text", None),
        ("hard_cap", "text", None),
        ("auto_polish_on_hard_cut", "bool", None),
    ]),
    ("文字加工", "Post-processing", [
        ("ppmode", "enum", "ppmode"),
        ("llm_mode", "enum", "llm_mode"),
        ("ollama_model", "ollama", None),
        ("online_base", "text", None),
        ("online_model", "text", None),
        ("online_key", "secret", None),
        ("llm_temperature", "text", None),
        ("llm_max_output_tokens", "text", None),
        ("llm_reasoning", "enum", "reasoning"),
        ("llm_strip_thinking", "bool", None),
        ("prompt_template", "textarea", None),
    ]),
]

# 每个分类的一句话说明（侧栏面板标题下方）。(中, 英)
_CAT_DESC = {
    "通用": ("界面语言与启动行为。",
            "Interface language and startup."),
    "语音识别": ("把语音转成文字的引擎。选好引擎后，只需填它自己的那几项。",
              "The speech-to-text engine. Pick one, then fill only its own fields."),
    "噪音过滤": ("识别前的噪音过滤：静音判定与底噪抑制，防把环境噪音误识别成短词（如“我。”）。仅在选用 适用于所有引擎。",
              "Pre-recognition noise filtering: silence gating & noise suppression. Works with all ASR engines."),
    "听写交互": ("如何触发听写、以及说完多久算一句结束。",
              "How to trigger dictation and when a sentence ends."),
    "智能断句": ("念稿/放录音等长时间不停顿时，自动逐步降低断句门槛，防止单段过长。",
              "For long non-stop speech: progressively relax cutting to avoid huge segments."),
    "文字加工": ("识别后的文字如何加工。选了润色/整理/翻译，才需在下方选大模型。",
              "How to process recognized text. The model below is only needed for polish/organize/translate."),
}

# 每个参数的帮助（缩进显示在控件下方）：①干什么 ②默认值与理由。(中, 英)
_HELP = {
    "language": (
        "界面与识别输出语言。默认中文。",
        "UI & recognition language. Default 中文."),
    "autostart": (
        "登录时自动启动。默认关闭。",
        "Launch at login. Default off."),
    "asr_engine": (
        "语音转文字引擎。默认本地 Whisper：离线、稳、免配置；SenseVoice 更快、自带标点。",
        "Speech-to-text engine. Default local Whisper (offline). SenseVoice is faster."),
    "whisper_model": (
        "仅本地 Whisper 用。tiny 快、medium 准。默认 small（速度精度平衡）。",
        "Local Whisper only. Default small (balanced)."),
    "mlx_model": (
        "仅 MLX Whisper 用（需 Apple 芯片）。默认 large-v3-turbo。",
        "MLX Whisper only (Apple Silicon). Default large-v3-turbo."),
    "dashscope_key_source": (
        "仅 Fun-ASR 用。env=读环境变量；manual=手填存钥匙串。默认 env。",
        "Fun-ASR only. env=env var; manual=keychain. Default env."),
    "dashscope_key": (
        "仅来源选 manual 时填。存入钥匙串，不写配置文件。",
        "Only when source=manual. Stored in keychain."),
    "asr_online_base": (
        "仅「在线 ASR」引擎使用。填局域网 SenseVoice 服务地址或 OpenAI 兼容 API 地址。"
        "例：http://192.168.1.10:8765/v1",
        "Online ASR engine only. E.g. http://192.168.1.10:8765/v1 or https://api.openai.com/v1"),
    "asr_online_model": (
        "在线 ASR 模型名。对接局域网 SenseVoice 服务可填任意字符串（服务端忽略）；"
        "对接 OpenAI 填 whisper-1。",
        "Model name for online ASR. For LAN SenseVoice server any string works; "
        "for OpenAI use whisper-1."),
    "asr_online_key": (
        "在线 ASR API Key。对接局域网自建服务可留空；对接 OpenAI 需填真实 Key。"
        "与「文字加工」的在线 Key 共用同一钥匙串项，留空保持不变。",
        "API key for online ASR. Leave empty for LAN server; needed for OpenAI. "
        "Shared keychain entry with Post-processing online key."),
    "force_filter": (
        "规范写法：只写文字，用英文逗号分隔，如 我,我的,我是,是的,Yeah。空格和其它标点会自动忽略。",
        "Recommended: text only, separated by English commas, e.g. 我,我的,我是,是的,Yeah. Spaces and punctuation are ignored."),
    "silence_threshold": (
        "RMS 静音阈值：越大越不易把底噪当人声、但太大会吞掉小声说话。默认 0.036。适用于所有引擎。",
        "RMS silence threshold: higher rejects more noise but may drop soft speech. Default 0.036. All engines."),
    "noise_filter": (
        "识别出短词却几乎没有真实语音(去掉静音后)时判为噪音、跳过注入（防“我。”幻觉）。适用于所有引擎。默认开启。",
        "Drop short text that has almost no real voiced audio (silence removed) — anti-hallucination. All engines. Default on."),
    "noise_min_voice_1char": (
        "识别出 1 个字，但去掉静音后的语音不足此秒数 → 判噪音。默认 0.05；填 0 = 1 字不拦截。",
        "1-char result with voiced audio (silence removed) shorter than this → noise. Default 0.05; 0=off."),
    "noise_min_voice_2char": (
        "识别出 2 个字时所需的最少语音时长。默认 0.05 秒；填 0 = 2 字不拦截。",
        "Min voiced seconds for 2-char results. Default 0.05s; 0=off."),
    "noise_min_voice_3char": (
        "识别出 3 个字时所需的最少语音时长。默认 0.07 秒；填 0 = 3 字不拦截。（4 字及以上一律不拦）",
        "Min voiced seconds for 3-char results. Default 0.07s; 0=off. (4+ chars never filtered.)"),
    "continuous": (
        "开启后双击 ⌘ 连续听写、按停顿自动分段。默认开启。",
        "On: double-tap ⌘ for continuous dictation. Default on."),
    "pause": (
        "停顿多久算一句说完。太短切碎、太长迟钝。默认 1.0 秒。",
        "Silence to end a segment. Default 1.0s."),
    "soft_cap": (
        "连续说话超此时长仍无停顿，开始放宽断句。默认 180 秒(3 分钟)；填 0 禁用。",
        "Start relaxing the cut after nonstop speech exceeds this. Default 180s; 0=off."),
    "soft_cap_step": (
        "进入探测后每隔此秒数把所需停顿减半（1.0→0.5→0.25…）。默认 60 秒。",
        "Halve the required pause every N seconds. Default 60s."),
    "hard_cap": (
        "一段到此时长强制切断，防内存溢出。默认 360 秒(6 分钟)。",
        "Force-cut at this length to prevent OOM. Default 360s."),
    "auto_polish_on_hard_cut": (
        "raw 模式下，强制切的段临时用 Ollama 润色补救。默认开启。"
        "⤷ 需在「文字加工」把大模型设为 Ollama 且服务可用。",
        "In raw mode, force-cut segments get a one-off Ollama polish. Default on. "
        "⤷ Needs the model in “Post-processing” set to Ollama."),
    "ppmode": (
        "识别文字如何加工。raw=直出；polish=纠错补标点(默认)；organize=整理；translate=翻译。",
        "raw=as-is; polish=fix typos (default); organize; translate."),
    "llm_mode": (
        "润色/整理/翻译用的大模型。ollama=本地(需先装)；online=在线 API。默认 ollama。",
        "LLM for polish/etc. ollama=local; online=API. Default ollama."),
    "ollama_model": (
        f"仅 ollama 用。选本地已装模型。默认 {DEFAULT_OLLAMA_MODEL}。"
        "⤷「智能断句」自动润色也用它。",
        f"ollama only. Default {DEFAULT_OLLAMA_MODEL}. ⤷ Also used by Smart Segmentation."),
    "online_base": (
        "在线大模型 API 地址。仅 online 用。",
        "Online API base URL. online only."),
    "online_model": (
        "在线大模型名，如 gpt-4o-mini。仅 online 用。",
        "Online model name. online only."),
    "online_key": (
        "在线大模型 Key。留空保持不变，存钥匙串。",
        "Online API key. Blank keeps current; in keychain."),
    "llm_temperature": (
        "控制大模型随机性。默认 0.0：语音输入要稳定、少改写原话；调高会更自由但更容易变意思。",
        "Controls randomness. Default 0.0: speech input should be stable and faithful; higher may rewrite more."),
    "llm_max_output_tokens": (
        "限制大模型最多输出多少 token。默认 512：足够普通听写加工，同时防异常长输出；填 0 表示不限制。",
        "Caps model output. Default 512: enough for dictation, prevents runaway output; 0 disables the cap."),
    "llm_reasoning": (
        "控制思考/推理模式。默认关闭：文字加工不需要长推理，可降低延迟并避免模型输出思考过程或改变表述。"
        "Ollama 会发送 think=false；DeepSeek 在线接口会发送 thinking=disabled。",
        "Reasoning mode. Default off: text polishing does not need long reasoning, reducing latency and drift. "
        "Ollama sends think=false; DeepSeek sends thinking=disabled."),
    "llm_strip_thinking": (
        "返回后清理 <think>...</think>、思考过程等内容。默认开启：即使模型不听参数，也只把最终文本输入到光标处。",
        "Remove <think>...</think> or reasoning text after response. Default on: only final text is inserted."),
    "prompt_template": (
        "当前显示的是实际生效的默认系统提示词，可直接修改。清空后恢复内置默认：纠错、补标点、保持原意、不回答问题、不输出解释。",
        "Shows the active default system prompt and can be edited directly. Clear it to restore the built-in default: "
        "fix typos/punctuation, keep meaning, do not answer or explain."),
    "denoise_enabled": (
        "启用 DeepFilterNet3 神经网络降噪：VAD 前先清理音频中的风扇/空调/键盘等环境噪声。"
        "需安装 onnxruntime 并下载模型。默认关闭。",
        "Enable DeepFilterNet3 neural denoising before VAD: removes fan/AC/keyboard noise. "
        "Requires onnxruntime and the model file. Default off."),
    "denoise_attenuation": (
        "降噪强度 0.0~1.0：越大降噪越狠、但也可能轻微损伤语音。默认 0.8。",
        "Denoising strength 0.0~1.0. Higher = stronger but may affect speech. Default 0.8."),
    "denoise_dry_wet_mix": (
        "干湿混合比 0.0~1.0：0=原音 1=纯降噪输出。默认 0.9（保留 10% 原始防过处理）。",
        "Dry/wet mix 0.0~1.0. 0=raw 1=fully denoised. Default 0.9 (keep 10% raw)."),
    "svr_port": (
        "SenseVoice ASR HTTP 服务监听端口（供局域网其他机器调用）。默认 18765。",
        "SenseVoice ASR HTTP server port for LAN sharing. Default 18765."),
    "svr_control": (
        "在本机启动/停止 SenseVoice ASR HTTP 服务。需 funasr + torch 环境。",
        "Start/stop the SenseVoice ASR HTTP server on this machine. Requires funasr + torch."),
}

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
_NOISE_ON = ("noise_filter", {True})
_DEPS = {
    "whisper_model": [("asr_engine", {"whisper_local"})],
    "mlx_model": [("asr_engine", {"mlx_whisper"})],
    "dashscope_key_source": [("asr_engine", {"dashscope"})],
    "dashscope_key":        [("asr_engine", {"dashscope"})],
    "asr_online_base":      [("asr_engine", {"online"})],
    "asr_online_model":     [("asr_engine", {"online"})],
    "asr_online_key":       [("asr_engine", {"online"})],
    # 1-3 字上限：「底噪幻觉拦截」开关打开才可编辑（不再限制引擎）
    "noise_min_voice_1char": [_NOISE_ON],
    "noise_min_voice_2char": [_NOISE_ON],
    "noise_min_voice_3char": [_NOISE_ON],
    "llm_mode": [_LLM_ACTIVE],                                    # 纯转写时禁用LLM引擎
    "ollama_model": [_LLM_ACTIVE, ("llm_mode", {"ollama"})],
    "online_base": [_LLM_ACTIVE, ("llm_mode", {"online"})],
    "online_model": [_LLM_ACTIVE, ("llm_mode", {"online"})],
    "online_key": [_LLM_ACTIVE, ("llm_mode", {"online"})],
    "llm_temperature": [_LLM_ACTIVE],
    "llm_max_output_tokens": [_LLM_ACTIVE],
    "llm_reasoning": [_LLM_ACTIVE],
    "llm_strip_thinking": [_LLM_ACTIVE],
    "prompt_template": [_LLM_ACTIVE],
}
_DRIVERS = ("asr_engine", "llm_mode", "ppmode", "noise_filter")

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


def _set_control_enabled(ctrl, enabled: bool) -> None:
    """启用/禁用设置控件，兼容多行文本框外层 NSScrollView。

    普通 Cocoa 控件有 setEnabled_；系统提示词多行编辑器是 NSScrollView 包
    NSTextView，外层没有 setEnabled_，需改内部 documentView 的可编辑状态。
    """
    try:
        if hasattr(ctrl, "setEnabled_"):
            ctrl.setEnabled_(enabled)
            return
        if hasattr(ctrl, "documentView"):
            doc = ctrl.documentView()
            if hasattr(doc, "setEditable_"):
                doc.setEditable_(enabled)
            if hasattr(doc, "setSelectable_"):
                doc.setSelectable_(True)
    except Exception:
        import logging
        _log = logging.getLogger(__name__)
        _log.debug("_set_control_enabled: 不支持的控件类型 %s (启用=%s)",
                   type(ctrl).__name__, enabled)


def _ollama_model_options(installed: list[str], current: str) -> list[str]:
    """构建 Ollama 模型下拉项；未安装当前模型时仍显示当前配置。"""
    opts = list(installed or [])
    if not opts:
        opts = ["(未检测到 / none)"]
    if current and current not in opts:
        opts = [current] + opts
    return opts


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

        def categoryClicked_(self, sender):
            fn = getattr(self, "_on_category", None)
            if fn is not None:
                fn(sender.tag())

        def noiseHistory_(self, _s):
            fn = getattr(self, "_on_noise_history", None)
            if fn is None:
                return
            try:
                fn()
            except Exception:
                # 自我兜底：拦截历史出错只记日志，绝不外泄到设置模态（否则会触发整窗失败提示）
                import logging
                logging.getLogger("voiceinput").exception("打开拦截历史失败")

        def forceFilterHistory_(self, _s):
            fn = getattr(self, "_on_force_filter_history", None)
            if fn is None:
                return
            try:
                fn()
            except Exception:
                import logging
                logging.getLogger("voiceinput").exception("打开强制过滤历史失败")

        def forceFilterRestore_(self, _s):
            """恢复强制过滤短语为默认值。"""
            from .config import AsrConfig
            defaults = ", ".join(AsrConfig.__dataclass_fields__[
                "force_filter_phrases"].default_factory())
            reg = getattr(self, "_reg", {})
            entry = reg.get("force_filter")
            if entry is not None:
                _, ctrl, _ = entry
                ctrl.setStringValue_(defaults)

        def svrToggle_(self, _s):
            """启动/停止 SenseVoice 服务，并刷新状态显示。"""
            from .svr_manager import status as svr_stat, start as svr_start, stop as svr_stop, SvrState
            # 防抖：禁用按钮，避免快速双击导致重复启动
            btn = getattr(self, "_svr_btn", None)
            if btn is not None:
                btn.setEnabled_(False)
            st, _ = svr_stat()
            if st == SvrState.RUNNING:
                ok, msg = svr_stop()
                action = "stop"
            else:
                ok, msg = svr_start()
                action = "start"
            # 刷新状态显示（内部会根据新状态重新启用按钮）
            fn = getattr(self, "_on_svr_refresh", None)
            if fn is not None:
                fn(ok, msg, action)
            if ok and st != SvrState.RUNNING:
                delayed = getattr(self, "_on_svr_delayed_refresh", None)
                if delayed is not None:
                    delayed()

        def svrTest_(self, _s):
            """测试 SenseVoice 服务健康状态。"""
            from .svr_manager import test_service

            lang = getattr(self, "_lang", "zh")
            ok, msg = test_service(lang)
            title = "测试服务" if lang == "zh" else "Test Service"
            _show_alert(title, msg)
            fn = getattr(self, "_on_svr_refresh", None)
            if fn is not None:
                fn(ok, msg)

        def downloadModel_(self, _s):
            """下载当前选中引擎的语音模型（仅本地引擎）。"""
            import logging
            from .config import load_config
            _log = logging.getLogger("voiceinput")
            try:
                c = load_config()
                eng = c.asr.engine
                if eng in ("dashscope", "online"):
                    _log.info("在线引擎 %s 无需下载模型", eng)
                    return
                from .asr import make_asr
                _log.info("开始下载/校验 %s 模型…", eng)
                a = make_asr(c)
                if hasattr(a, "_ensure_model"):
                    a._ensure_model()
                _log.info("%s 模型已就绪 ✓", eng)
            except Exception as e:
                _log.exception("模型下载失败: %s", e)

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

    W, H = 600, 480
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    nsapp.activateIgnoringOtherApps_(True)

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    win.setReleasedWhenClosed_(False)  # 防 PyObjC 二次释放段错误（见设置窗口注释）
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
    ctl._lang = lang
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
    """侧边栏导航 + 右侧自包含面板（仿 macOS 系统设置）。"""
    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory,
        NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
        NSBezelStyleRounded, NSBox, NSButton, NSColor, NSFont,
        NSPopUpButton, NSScrollView, NSSwitch, NSTextField, NSTextView, NSView, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect

    from . import app as appmod
    from .config import get_api_key

    _ensure_edit_menu()  # 装「编辑」菜单，使文本框 ⌘V 粘贴可用

    lang = app.cfg.general.language
    li = 0 if lang == "zh" else 1

    # ---- 尺寸 ----
    from AppKit import NSScreen
    _vf = NSScreen.mainScreen().visibleFrame()
    W = max(720, int(_vf.size.width  * 0.618))
    H = max(560, int(_vf.size.height * 0.618))
    btn_h = 56
    sb_w = 190                       # 侧边栏宽
    dx = sb_w + 1                    # 详情区左边界
    dw = W - dx                      # 详情区宽
    dh = H - btn_h                   # 详情区高
    ipad = 24                        # 面板内边距
    lab_w = 150                      # 字段标签宽
    cx = ipad + lab_w + 12           # 控件 x（面板内，即「第二列」）
    cw = dw - cx - ipad              # 控件/帮助宽
    help_h = 42                      # 帮助文字高（≤2 行，缩进在第二列）
    field_block = 82                 # 每个字段（标签+控件+帮助）占高

    def control_height(kind: str) -> int:
        return 96 if kind == "textarea" else 24

    def block_height(kind: str) -> int:
        return 156 if kind == "textarea" else field_block

    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    nsapp.activateIgnoringOtherApps_(True)

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    # 关键：阻止 AppKit 在关窗时释放窗口（默认 YES），否则与 PyObjC 的释放
    # 叠加成二次释放，关闭动画清池时 EXC_BAD_ACCESS 段错误。
    win.setReleasedWhenClosed_(False)
    win.setTitle_("设置" if lang == "zh" else "Settings")
    content = win.contentView()

    ctl = _get_controller_class().alloc().init()
    win.setDelegate_(ctl)

    def mk_label(parent, text, x, y, w, h=18, bold=False, secondary=False,
                 size=12, wrap=False):
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        f.setStringValue_(text)
        f.setBezeled_(False)
        f.setDrawsBackground_(False)
        f.setEditable_(False)
        f.setSelectable_(False)
        f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                   else NSFont.systemFontOfSize_(size))
        if secondary:
            f.setTextColor_(NSColor.secondaryLabelColor())
        if wrap:
            f.cell().setWraps_(True)
        parent.addSubview_(f)
        return f

    reg = {}  # field_id -> (kind, control, enum)；跨所有面板，供 _apply/联动统一读取

    def build_control(parent, fid, kind, enum, ctl_x, ctl_y):
        cur = app._field_get(fid)
        if kind == "enum":
            c = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctl_x, ctl_y, cw, 26), False)
            titles = [it[1] if li == 0 else it[2] for it in appmod._ENUMS[enum]]
            c.addItemsWithTitles_(titles)
            c.selectItemWithTitle_(appmod._enum_display(enum, cur, lang))
        elif kind == "bool":
            c = NSSwitch.alloc().initWithFrame_(NSMakeRect(ctl_x, ctl_y, 44, 24))
            c.setState_(1 if cur else 0)
        elif kind == "pause":
            c = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctl_x, ctl_y, 120, 26), False)
            opts = list(_PAUSE_PRESETS)
            cs = ("%g" % float(cur))
            if cs not in opts:
                opts = [cs] + opts
            c.addItemsWithTitles_([f"{o} 秒" for o in opts])
            c.selectItemWithTitle_(f"{cs} 秒")
        elif kind in ("whisper", "ollama", "mlx"):
            c = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(ctl_x, ctl_y, cw, 26), False)
            if kind == "whisper":
                opts = list(_WHISPER_PRESETS)
            elif kind == "mlx":
                opts = list(_MLX_PRESETS)
            else:
                opts = _ollama_model_options(appmod.list_ollama_models(app.cfg), cur)
            c.addItemsWithTitles_(opts)
            if cur:
                c.selectItemWithTitle_(cur)
        elif kind == "svr":
            # SenseVoice 服务：状态主行 + 详情行 + 启动/停止按钮
            from .svr_manager import server_info, SvrState
            info = server_info()
            running = (info.state == SvrState.RUNNING)
            unsup = (info.state == SvrState.UNSUPPORTED)

            if running:
                if info.health_ok:
                    st_line = ("运行中 · PID %d · 端口 %d" if li == 0
                               else "Running · PID %d · Port %d")
                else:
                    st_line = ("启动中 · PID %d · 端口 %d" if li == 0
                               else "Starting · PID %d · Port %d")
                st_line = st_line % (info.pid, info.port)
                detail_line = ("日志: %s · 进程: %s" if li == 0
                               else "Log: %s · Process: %s")
                detail_line = detail_line % (info.log_file, info.process_name)
            elif unsup:
                st_line = "本机不支持" if li == 0 else "Unsupported"
                detail_line = ""
            else:
                st_line = "已停止" if li == 0 else "Stopped"
                detail_line = ""
            btn_text = "停止服务" if running else "启动服务"
            if li == 1:
                btn_text = "Stop" if running else "Start"

            # 状态标签（主行）
            c = mk_label(parent, st_line, ctl_x, ctl_y, cw - 200, 22,
                         secondary=True, size=12)
            st_color = (0.2, 0.7, 0.2, 1.0) if running else (
                       (0.5, 0.5, 0.5, 1.0))
            from AppKit import NSColor
            c.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(*st_color))

            # 详情行（运行时/异常时显示）
            ctl._svr_detail = None
            if detail_line:
                d = mk_label(parent, detail_line, ctl_x, ctl_y - 18,
                             cw - 200, 16, secondary=True, size=10)
                ctl._svr_detail = d

            # 启动/停止 + 测试按钮
            test_btn_w = 86
            btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(ctl_x + cw - 190, ctl_y - 2, 92, 28))
            btn.setTitle_(btn_text)
            btn.setBezelStyle_(NSBezelStyleRounded)
            btn.setFont_(NSFont.systemFontOfSize_(12))
            btn.setTarget_(ctl)
            btn.setAction_("svrToggle:")
            btn.setEnabled_(not unsup)
            parent.addSubview_(btn)
            ctl._svr_btn = btn
            tb = NSButton.alloc().initWithFrame_(
                NSMakeRect(ctl_x + cw - test_btn_w, ctl_y - 2, test_btn_w, 28))
            tb.setTitle_("测试服务" if li == 0 else "Test")
            tb.setBezelStyle_(NSBezelStyleRounded)
            tb.setFont_(NSFont.systemFontOfSize_(12))
            tb.setTarget_(ctl)
            tb.setAction_("svrTest:")
            tb.setEnabled_(not unsup)
            parent.addSubview_(tb)
            ctl._svr_test_btn = tb
        elif kind in ("text", "secret"):
            c = NSTextField.alloc().initWithFrame_(
                NSMakeRect(ctl_x, ctl_y, cw, 24))
            if kind == "secret":
                # 已存 Key 用占位符表示（不明文暴露）；留占位符=保持不变
                c.setStringValue_(app._KEY_PLACEHOLDER if get_api_key() else "")
            elif isinstance(cur, float):
                c.setStringValue_("%g" % cur)   # 数值字段：0 显示 "0"，180.0 显示 "180"
            else:
                c.setStringValue_(str(cur or ""))
        elif kind == "textarea":
            c = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(ctl_x, ctl_y - 72, cw, 96))
            c.setHasVerticalScroller_(True)
            c.setAutohidesScrollers_(True)
            c.setBorderType_(1)  # NSLineBorder
            tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, 96))
            tv.setVerticallyResizable_(True)
            tv.setHorizontallyResizable_(False)
            tv.textContainer().setWidthTracksTextView_(True)
            tv.setFont_(NSFont.systemFontOfSize_(12))
            tv.setString_(str(cur or ""))
            c.setDocumentView_(tv)
        else:
            return None
        parent.addSubview_(c)
        return c

    # ---- 为每个分类构建一个自包含面板 ----
    from Foundation import NSMakePoint
    panels = []
    for (name_zh, name_en, fields) in _CATEGORIES:
        _desc_tmp = _CAT_DESC.get(name_zh, ("", ""))
        _has_desc = bool(_desc_tmp[0] or _desc_tmp[1])
        content_h = max(
            dh,
            58 + (38 if _has_desc else 0) + 28
            + sum(block_height(kind) for _fid, kind, _enum in fields) + 20,
        )
        panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, dw, content_h))
        _sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(dx, btn_h, dw, dh))
        _sv.setDocumentView_(panel)
        _sv.setHasVerticalScroller_(True)
        _sv.setAutohidesScrollers_(True)
        _sv.setBorderType_(0)  # NSNoBorder
        _sv.setDrawsBackground_(False)
        y = content_h - 28
        mk_label(panel, name_zh if li == 0 else name_en, ipad, y,
                 dw - 2 * ipad, 26, bold=True, size=17)
        y -= 30
        desc = _CAT_DESC.get(name_zh, ("", ""))[li]
        if desc:
            mk_label(panel, desc, ipad, y - 14, dw - 2 * ipad, 32,
                     secondary=True, size=11, wrap=True)
            y -= 38
        sep = NSBox.alloc().initWithFrame_(NSMakeRect(ipad, y, dw - 2 * ipad, 1))
        sep.setBoxType_(2)  # NSBoxSeparator
        panel.addSubview_(sep)
        y -= 28                       # 配置内容与分隔线留出距离

        for fid, kind, enum in fields:
            label = appmod._LABELS[fid][li]
            mk_label(panel, label, ipad, y - 4, lab_w, 18, size=12)
            c = build_control(panel, fid, kind, enum, cx, y - 6)
            if c is None:
                y -= block_height(kind)
                continue
            _set_a11y(c, label)
            reg[fid] = (kind, c, enum)
            # 「底噪幻觉拦截」开关右侧：拦截历史按钮（仅展示被拦片段）
            if fid == "noise_filter":
                hb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(cx + 60, y - 9, 120, 28))
                hb.setTitle_("拦截历史" if li == 0 else "History")
                hb.setBezelStyle_(NSBezelStyleRounded)
                hb.setFont_(NSFont.systemFontOfSize_(12))
                hb.setTarget_(ctl)
                hb.setAction_("noiseHistory:")   # ObjC 选择器用冒号（noiseHistory_ 方法→noiseHistory:）
                panel.addSubview_(hb)
            # ASR 引擎右侧：「下载模型」按钮（仅本地引擎需要）
            if fid == "asr_engine":
                btn_w = 86
                c.setFrame_(NSMakeRect(cx, y - 6, cw - btn_w - 8, 26))
                db = NSButton.alloc().initWithFrame_(
                    NSMakeRect(cx + cw - btn_w, y - 6, btn_w, 26))
                db.setTitle_("下载模型" if li == 0 else "Download")
                db.setBezelStyle_(NSBezelStyleRounded)
                db.setFont_(NSFont.systemFontOfSize_(12))
                db.setTarget_(ctl)
                db.setAction_("downloadModel:")
                panel.addSubview_(db)
            # 强制过滤文本框右侧：恢复默认 + 历史记录按钮
            if fid == "force_filter":
                btn_w = 86
                gap = 8
                # 文本框缩窄，给两个按钮腾位置
                c.setFrame_(NSMakeRect(cx, y - 6,
                           cw - 2 * btn_w - gap * 2, 24))
                # 恢复默认按钮
                rb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(cx + cw - 2 * btn_w - gap, y - 9, btn_w, 28))
                rb.setTitle_("恢复默认" if li == 0 else "Restore")
                rb.setBezelStyle_(NSBezelStyleRounded)
                rb.setFont_(NSFont.systemFontOfSize_(12))
                rb.setTarget_(ctl)
                rb.setAction_("forceFilterRestore:")
                panel.addSubview_(rb)
                # 历史记录按钮
                hb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(cx + cw - btn_w, y - 9, btn_w, 28))
                hb.setTitle_("历史记录" if li == 0 else "History")
                hb.setBezelStyle_(NSBezelStyleRounded)
                hb.setFont_(NSFont.systemFontOfSize_(12))
                hb.setTarget_(ctl)
                hb.setAction_("forceFilterHistory:")
                panel.addSubview_(hb)
            # 帮助文字缩进对齐到第二列（控件下方），不占第一列
            htxt = _HELP.get(fid, ("", ""))[li]
            if htxt:
                control_bottom = y - 6 - max(0, control_height(kind) - 24)
                mk_label(panel, htxt, cx, control_bottom - help_h, cw, help_h,
                         secondary=True, size=11, wrap=True)
            y -= block_height(kind)

        panel.scrollPoint_(NSMakePoint(0, max(0, content_h - dh)))
        _sv.setHidden_(True)
        content.addSubview_(_sv)
        panels.append(_sv)

    # ---- 侧边栏：竖分隔线 + 选中高亮 + 分类行 ----
    vdiv = NSBox.alloc().initWithFrame_(NSMakeRect(sb_w, btn_h, 1, dh))
    vdiv.setBoxType_(2)  # NSBoxSeparator
    content.addSubview_(vdiv)

    row_h_s, row_gap = 30, 4
    top_y = H - 16
    row_ys = []
    hl = NSBox.alloc().initWithFrame_(NSMakeRect(6, top_y, sb_w - 12, row_h_s))
    hl.setBoxType_(4)  # NSBoxCustom
    hl.setBorderWidth_(0.0)
    hl.setCornerRadius_(6.0)
    hl.setFillColor_(NSColor.colorWithCalibratedWhite_alpha_(0.5, 0.16))
    content.addSubview_(hl)  # 先加 → 在行按钮之下

    for i, (name_zh, name_en, _f) in enumerate(_CATEGORIES):
        ry = top_y - row_h_s - i * (row_h_s + row_gap)
        row_ys.append(ry)
        b = NSButton.alloc().initWithFrame_(
            NSMakeRect(10, ry, sb_w - 20, row_h_s))
        b.setTitle_("  " + (name_zh if li == 0 else name_en))
        b.setBordered_(False)
        b.setButtonType_(0)          # NSButtonTypeMomentaryLight
        b.setAlignment_(0)           # NSTextAlignmentLeft
        b.setFont_(NSFont.systemFontOfSize_(13))
        b.setTag_(i)
        b.setTarget_(ctl)
        b.setAction_("categoryClicked:")
        content.addSubview_(b)

    def select_category(idx):
        for p in panels:
            p.setHidden_(True)
        panels[idx].setHidden_(False)
        hl.setFrame_(NSMakeRect(6, row_ys[idx] - 1, sb_w - 12, row_h_s + 2))

    ctl._on_category = select_category
    ctl._on_noise_history = lambda: _open_history_window(app)
    ctl._on_force_filter_history = lambda: _open_force_filter_history_window(app)
    ctl._reg = reg          # 字段注册表，供 forceFilterRestore_ 等按钮使用
    if not hasattr(ctl, "_svr_btn"):
        ctl._svr_btn = None     # SenseVoice 按钮引用，供 _refresh_svr_status 更新
    if not hasattr(ctl, "_svr_test_btn"):
        ctl._svr_test_btn = None
    select_category(0)

    # ---- 联动：驱动项变化时启用/禁用相关字段（跨面板统一刷新）----
    def _refresh_enabled():
        cur = {}
        for drv in _DRIVERS:
            if drv in reg:
                kind, c, en = reg[drv]
                # 开关驱动(bool)读其开/关状态；下拉驱动(enum)解析所选项
                cur[drv] = (c.state() == 1) if kind == "bool" \
                    else appmod._enum_parse(en, c.titleOfSelectedItem())
        for fid, conds in _DEPS.items():
            if fid in reg:
                enabled = all(cur.get(driver) in allowed
                              for driver, allowed in conds)
                _set_control_enabled(reg[fid][1], enabled)

    for drv in _DRIVERS:
        if drv in reg:
            reg[drv][1].setTarget_(ctl)
            reg[drv][1].setAction_("driverChanged:")
    ctl._refresh = _refresh_enabled
    _refresh_enabled()

    # SenseVoice 服务状态刷新：更新三元素——主标签、详情行、按钮
    def _refresh_svr_status(ok: bool = True, msg: str = "", action: str = "") -> None:
        from .svr_manager import server_info, SvrState
        from AppKit import NSColor
        entry = reg.get("svr_control")
        if entry is None:
            return
        _, sl, _ = entry
        info = server_info()
        running = (info.state == SvrState.RUNNING)
        active = running or (ok and action == "start")
        unsup = (info.state == SvrState.UNSUPPORTED)

        if running:
            if info.health_ok:
                st_line = ("运行中 · PID %d · 端口 %d" if li == 0
                           else "Running · PID %d · Port %d")
            else:
                st_line = ("启动中 · PID %d · 端口 %d" if li == 0
                           else "Starting · PID %d · Port %d")
            st_line = st_line % (info.pid, info.port)
            detail_line = ("日志: %s · 进程: %s" if li == 0
                           else "Log: %s · Process: %s")
            detail_line = detail_line % (info.log_file, info.process_name)
        elif ok and action == "start":
            st_line = "启动中" if li == 0 else "Starting"
            detail_line = msg or ""
        elif unsup:
            st_line = "本机不支持" if li == 0 else "Unsupported"
            detail_line = ""
        else:
            st_line = "已停止" if li == 0 else "Stopped"
            detail_line = ""
        sl.setStringValue_(st_line)
        st_color = (0.2, 0.7, 0.2, 1.0) if active else (
                   (0.5, 0.5, 0.5, 1.0))
        sl.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(*st_color))
        # 更新详情行
        if hasattr(ctl, "_svr_detail") and ctl._svr_detail is not None:
            if detail_line:
                ctl._svr_detail.setStringValue_(detail_line)
                ctl._svr_detail.setHidden_(False)
            else:
                ctl._svr_detail.setHidden_(True)
        btn_text = "停止服务" if active else "启动服务"
        if li == 1:
            btn_text = "Stop" if running else "Start"
        svr_btn = getattr(ctl, "_svr_btn", None)
        if svr_btn is not None:
            svr_btn.setTitle_(btn_text)
            svr_btn.setEnabled_(not unsup)  # 操作完成后恢复按钮
        test_btn = getattr(ctl, "_svr_test_btn", None)
        if test_btn is not None:
            test_btn.setEnabled_(not unsup)

    ctl._on_svr_refresh = _refresh_svr_status

    def _schedule_svr_delayed_refresh() -> None:
        """服务启动成功后分 3 个时间点刷新状态显示。

        NSTimer 在主线程 RunLoop 触发，确保所有 AppKit UI 操作安全。
        threading.Timer 在后台线程回调，操作 Cocoa 控件为未定义行为。
        """
        from Foundation import NSObject, NSTimer

        class _SvrRefreshHelper(NSObject):
            def doRefresh_(self, timer):
                _refresh_svr_status()

        helper = _SvrRefreshHelper.alloc().init()
        for delay in (0.5, 1.5, 3.0):
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                delay, helper, "doRefresh:", None, False)

    ctl._on_svr_delayed_refresh = _schedule_svr_delayed_refresh

    # ---- 底部按钮栏 ----
    def mk_btn(title, x, sel, default=False):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, 13, 120, 30))
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
    mk_btn(restore_t, 20, "restore:")
    mk_btn(cancel_t, W - 20 - 250, "cancel:")
    mk_btn(save_t, W - 20 - 120, "save:", default=True)

    # 真正上下+左右居中（center() 仅水平居中，垂直偏上）
    _vf2 = NSScreen.mainScreen().visibleFrame()
    from Foundation import NSMakePoint
    _cx = _vf2.origin.x + (_vf2.size.width  - W) / 2
    _cy = _vf2.origin.y + (_vf2.size.height - H) / 2
    win.setFrameOrigin_(NSMakePoint(_cx, _cy))
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


def _open_history_window(app) -> None:
    """「拦截历史」窗口：只展示被底噪幻觉拦截、跳过注入的片段。

    每条含：拦截时间、对应音频时长、字数、被拦的识别文本。其余日志一律不显示。
    作为嵌套模态运行在设置窗口之上，关闭后返回设置窗口。
    """
    from AppKit import (
        NSApplication, NSBackingStoreBuffered, NSBezelStyleRounded, NSButton,
        NSFont, NSScrollView, NSTextView, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect, NSMakeSize

    from . import noise_history

    zh = app.cfg.general.language == "zh"
    recs = noise_history.load()

    if zh:
        title, close_t = "拦截历史", "关闭"
        head = "以下片段被判为底噪幻觉、已跳过注入（仅此一类，不含其他日志）：\n"
        cols = "时间                       语音    段长   字数   内容"
        empty = "暂无拦截记录。"
        total = f"\n\n共 {len(recs)} 条"
    else:
        title, close_t = "Interception History", "Close"
        head = "Segments dropped as background-noise hallucination (this only):\n"
        cols = "Time                       Voice   Seg    Chars  Content"
        empty = "No interceptions yet."
        total = f"\n\n{len(recs)} total"

    lines = []
    for r in recs:
        tstr = r.get("ts", "?")                       # 日志已是 "YYYY-MM-DD HH:MM:SS"
        v = r.get("voiced")
        vstr = f"{float(v):>5.2f}s" if v is not None else "  -  "  # 旧记录无语音时长
        seg = float(r.get("seg", 0) or 0)
        chars = r.get("chars", 0)
        txt = (r.get("text", "") or "").replace("\n", " ")
        quote = f"「{txt}」" if zh else f"\"{txt}\""
        lines.append(f"{tstr}   {vstr}   {seg:>4.1f}s   {chars:>3}   {quote}")
    body = head + "\n" + cols + "\n" + ("-" * 64) + "\n"
    body += ("\n".join(lines) if lines else empty) + total

    W, H = 640, 520
    nsapp = NSApplication.sharedApplication()
    style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
             | NSWindowStyleMaskResizable)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    win.setReleasedWhenClosed_(False)  # 防 PyObjC 二次释放段错误
    win.setTitle_(title)
    content = win.contentView()

    hctl = _get_controller_class().alloc().init()
    win.setDelegate_(hctl)

    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(16, 56, W - 32, H - 72))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(2)  # NSBezelBorder
    scroll.setAutohidesScrollers_(True)
    tv = NSTextView.alloc().initWithFrame_(
        NSMakeRect(0, 0, W - 32, H - 72))
    tv.setEditable_(False)
    tv.setSelectable_(True)
    tv.setVerticallyResizable_(True)
    tv.setMinSize_(NSMakeSize(0, 0))
    tv.setMaxSize_(NSMakeSize(1e7, 1e7))
    tv.textContainer().setWidthTracksTextView_(True)
    mono = NSFont.fontWithName_size_("Menlo", 12) or NSFont.systemFontOfSize_(12)
    tv.setFont_(mono)
    tv.setString_(body)
    scroll.setDocumentView_(tv)
    content.addSubview_(scroll)

    btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 120, 14, 100, 30))
    btn.setTitle_(close_t)
    btn.setBezelStyle_(NSBezelStyleRounded)
    btn.setKeyEquivalent_("\r")
    btn.setTarget_(hctl)
    btn.setAction_("cancel:")            # 复用：停止本层模态
    content.addSubview_(btn)

    win.center()
    win.makeKeyAndOrderFront_(None)
    nsapp.runModalForWindow_(win)        # 嵌套模态：在设置窗口之上
    win.orderOut_(None)



def _open_force_filter_history_window(app) -> None:
    """「强制过滤历史」窗口：展示被强制过滤命中、跳过注入的识别结果。"""
    from AppKit import (
        NSApplication, NSBackingStoreBuffered, NSBezelStyleRounded, NSButton,
        NSFont, NSScrollView, NSTextView, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect, NSMakeSize

    from . import force_filter_history

    zh = app.cfg.general.language == "zh"
    recs = force_filter_history.load()

    if zh:
        title, close_t = "强制过滤历史", "关闭"
        head = "以下识别结果被强制过滤命中、已跳过注入：\n"
        cols = "时间                         内容"
        empty = "暂无强制过滤记录。"
        total = f"\n\n共 {len(recs)} 条"
    else:
        title, close_t = "Force-filter History", "Close"
        head = "Segments dropped by force-filter:\n"
        cols = "Time                         Content"
        empty = "No force-filter events yet."
        total = f"\n\n{len(recs)} total"

    lines = []
    for r in recs:
        tstr = r.get("ts", "?")
        txt = (r.get("text", "") or "").replace("\n", " ")
        quote = f"「{txt}」" if zh else f'"{txt}"'
        lines.append(f"{tstr}   {quote}")
    body = head + "\n" + cols + "\n" + ("-" * 52) + "\n"
    body += ("\n".join(lines) if lines else empty) + total

    W, H = 600, 440
    nsapp = NSApplication.sharedApplication()
    style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
             | NSWindowStyleMaskResizable)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
    win.setReleasedWhenClosed_(False)
    win.setTitle_(title)
    content = win.contentView()

    hctl = _get_controller_class().alloc().init()
    win.setDelegate_(hctl)

    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(16, 56, W - 32, H - 72))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(2)
    scroll.setAutohidesScrollers_(True)
    tv = NSTextView.alloc().initWithFrame_(
        NSMakeRect(0, 0, W - 32, H - 72))
    tv.setEditable_(False)
    tv.setSelectable_(True)
    tv.setVerticallyResizable_(True)
    tv.setMinSize_(NSMakeSize(0, 0))
    tv.setMaxSize_(NSMakeSize(1e7, 1e7))
    tv.textContainer().setWidthTracksTextView_(True)
    mono = NSFont.fontWithName_size_("Menlo", 12) or NSFont.systemFontOfSize_(12)
    tv.setFont_(mono)
    tv.setString_(body)
    scroll.setDocumentView_(tv)
    content.addSubview_(scroll)

    btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 120, 14, 100, 30))
    btn.setTitle_(close_t)
    btn.setBezelStyle_(NSBezelStyleRounded)
    btn.setKeyEquivalent_("\r")
    btn.setTarget_(hctl)
    btn.setAction_("cancel:")
    content.addSubview_(btn)

    win.center()
    win.makeKeyAndOrderFront_(None)
    nsapp.runModalForWindow_(win)
    win.orderOut_(None)


def _show_alert(title: str, msg: str) -> None:
    """弹一个原生提示框（保存阶段告知用户某项无法应用）。"""
    try:
        from AppKit import NSAlert
        a = NSAlert.alloc().init()
        a.setMessageText_(title)
        a.setInformativeText_(msg)
        a.runModal()
    except Exception:
        pass


def _apply(app, reg: dict) -> None:
    import logging

    from . import app as appmod
    from .config import save_config

    lang = app.cfg.general.language
    for fid, (kind, ctrl, enum) in reg.items():
        # 每个字段独立 try：单项出错（如数值框输入非法）只跳过该项，
        # 绝不让一次保存整体失败、丢掉其它已改设置。
        try:
            if kind == "enum":
                internal = appmod._enum_parse(enum, ctrl.titleOfSelectedItem())
                if internal is not None:
                    app._field_set(fid, internal)
            elif kind == "bool":
                val = ctrl.state() == 1
                if fid == "autostart":
                    app.apply_autostart(val)   # 真正写/删 LaunchAgent
                elif fid == "auto_polish_on_hard_cut":
                    # 手动开启时检测 Ollama，不可用则提示并保持关闭
                    if val and not app._ollama_available():
                        _show_alert(
                            "无法开启自动润色" if lang == "zh"
                            else "Cannot enable auto-polish",
                            "未检测到可用的本地 Ollama 服务，已保持关闭。\n"
                            "请先启动 Ollama，并在「文字加工」把大模型设为 Ollama。"
                            if lang == "zh" else
                            "Local Ollama is not reachable; kept off.\n"
                            "Start Ollama and set the model to Ollama in Post-processing.")
                        app.cfg.vad.auto_polish_on_hard_cut = False
                    else:
                        app.cfg.vad.auto_polish_on_hard_cut = val
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
            elif kind == "svr":
                pass  # 纯 UI 控件（状态显示+按钮），不参与保存
            elif kind in ("text", "secret"):
                app._field_set(fid, ctrl.stringValue().strip())
            elif kind == "textarea":
                app._field_set(fid, ctrl.documentView().string().strip())
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "设置项 %s 保存失败(已跳过): %s", fid, exc)

    app._asr = None
    save_config(app.cfg)
