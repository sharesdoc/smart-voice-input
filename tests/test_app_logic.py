"""应用层逻辑测试（不进入 rumps 事件循环）。

VoiceInputApp 构造不导入 rumps（懒加载于 build()），故可在无 GUI 环境测试。
"""

import sys
import types

from voiceinput.app import VoiceInputApp
from voiceinput.config import DEFAULT_OLLAMA_MODEL, Config
from voiceinput.state import AppState


def _drive_to_refining(app: VoiceInputApp):
    app._sm.transition(AppState.LISTENING)
    app._sm.transition(AppState.TRANSCRIBING)
    app._sm.transition(AppState.REFINING)


def test_set_state_idle_uses_force():
    """pipeline 回调 'IDLE' 应能从任意状态强制回到空闲。"""
    app = VoiceInputApp(cfg=Config())
    _drive_to_refining(app)
    app._set_state("IDLE")
    assert app._sm.state == AppState.IDLE


def test_effective_vad_caps_clamps_online_engine():
    """在线引擎(dashscope/online)软封顶上限被收紧到安全值(25/40s)，防超时整段失败。"""
    # 在线引擎：默认 480/600 被收紧
    assert VoiceInputApp._effective_vad_caps("dashscope", 480.0, 600.0) == (25.0, 40.0)
    assert VoiceInputApp._effective_vad_caps("online", 480.0, 600.0) == (25.0, 40.0)
    # 在线引擎已配更小值则保留（取 min）
    assert VoiceInputApp._effective_vad_caps("online", 10.0, 20.0) == (10.0, 20.0)
    # 在线引擎且禁用(0)→ 回落到安全上限而非保持禁用
    assert VoiceInputApp._effective_vad_caps("dashscope", 0.0, 0.0) == (25.0, 40.0)


def test_effective_vad_caps_local_engine_untouched():
    """本地引擎保留配置原值，不收紧。"""
    assert VoiceInputApp._effective_vad_caps("sensevoice", 480.0, 600.0) == (480.0, 600.0)
    assert VoiceInputApp._effective_vad_caps("whisper_local", 480.0, 600.0) == (480.0, 600.0)
    assert VoiceInputApp._effective_vad_caps("mlx_whisper", 0.0, 0.0) == (0.0, 0.0)


def test_error_alert_second_button_opens_log(monkeypatch):
    class FakeAlert:
        def __init__(self):
            self.buttons = []

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setMessageText_(self, _text):
            pass

        def setInformativeText_(self, _text):
            pass

        def addButtonWithTitle_(self, title):
            self.buttons.append(title)

        def runModal(self):
            return 1001  # 第二个按钮：查看日志

    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(NSAlert=FakeAlert))
    app = VoiceInputApp(cfg=Config())
    opened = {"log": False}
    app._activate = lambda: None
    app._deactivate = lambda: None
    app._open_log = lambda _s=None: opened.update(log=True)

    app._error_alert_with_log_button("系统配置", "错误")

    assert opened["log"] is True


def test_default_ollama_model_missing_message(monkeypatch):
    app = VoiceInputApp(cfg=Config())
    monkeypatch.setattr(app, "available_ollama_models", lambda: ["qwen3:8b"])

    msg = app.default_ollama_model_missing_message()

    assert DEFAULT_OLLAMA_MODEL in msg
    assert f"ollama pull {DEFAULT_OLLAMA_MODEL}; ollama list" in msg


def test_default_ollama_model_installed_has_no_warning(monkeypatch):
    app = VoiceInputApp(cfg=Config())
    monkeypatch.setattr(app, "available_ollama_models", lambda: [DEFAULT_OLLAMA_MODEL])

    assert app.default_ollama_model_missing_message() == ""


def test_default_ollama_model_warning_skips_raw_mode(monkeypatch):
    app = VoiceInputApp(cfg=Config())
    app.cfg.postprocess.mode = "raw"
    monkeypatch.setattr(app, "available_ollama_models", lambda: [])

    assert app.default_ollama_model_missing_message() == ""
