"""设置应用逻辑测试 (FR-11/FR-12)。

验证 VoiceInputApp 的 apply_* 方法正确改配置并持久化，无需 rumps。
"""

import pytest

from voiceinput.app import VoiceInputApp, parse_online_form
from voiceinput.config import Config, load_config


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    return VoiceInputApp(cfg=Config())


def test_apply_postprocess_mode_persists(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app.apply_postprocess_mode("translate")
    assert app.cfg.postprocess.mode == "translate"
    assert load_config().postprocess.mode == "translate"


def test_apply_llm_mode_persists(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app.apply_llm_mode("online")
    assert load_config().llm.mode == "online"


def test_apply_ollama_model(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app.apply_ollama_model("llama3.1:8b")
    assert load_config().llm.ollama.model == "llama3.1:8b"


def test_apply_whisper_model_invalidates_cache(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app._asr = object()  # 假装已缓存
    app.apply_whisper_model("medium")
    assert app._asr is None  # 缓存被清除
    assert load_config().asr.whisper_model == "medium"


def test_apply_online_settings(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app.apply_online_setting("base_url", "https://api.deepseek.com/v1")
    app.apply_online_setting("model", "deepseek-chat")
    cfg = load_config()
    assert cfg.llm.online.base_url == "https://api.deepseek.com/v1"
    assert cfg.llm.online.model == "deepseek-chat"


def _capture_alert(app):
    """拦截弹窗，返回 (title, message)。"""
    cap = {}
    app._activate = lambda: None
    app._alert = lambda title, msg: cap.update(title=title, msg=msg)
    return cap


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_view_config_renders_nonempty(lang, tmp_path, monkeypatch):
    """查看配置必须弹出非空内容（回归：tr 参数与 {lang} 占位符撞名导致空白）。"""
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    cfg = Config()
    cfg.general.language = lang
    app = VoiceInputApp(cfg=cfg)
    cap = _capture_alert(app)
    app._open_settings(None)  # 不应抛异常
    assert cap.get("title")
    assert cap.get("msg") and len(cap["msg"]) > 10
    assert "{" not in cap["msg"]  # 占位符必须已被替换


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_about_renders_nonempty(lang, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    cfg = Config()
    cfg.general.language = lang
    app = VoiceInputApp(cfg=cfg)
    cap = _capture_alert(app)
    app._about(None)
    assert cap.get("msg") and "{" not in cap["msg"]


def test_parse_online_form():
    form = parse_online_form(
        "base_url=https://x/v1\nmodel=gpt-4o-mini\napi_key=sk-abc\n# comment\nbad line")
    assert form["base_url"] == "https://x/v1"
    assert form["model"] == "gpt-4o-mini"
    assert form["api_key"] == "sk-abc"
    assert "bad line" not in form


def test_apply_online_form_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app._apply_online_form("base_url=https://api.deepseek.com/v1\nmodel=deepseek-chat\napi_key=")
    cfg = load_config()
    assert cfg.llm.online.base_url == "https://api.deepseek.com/v1"
    assert cfg.llm.online.model == "deepseek-chat"


def test_apply_online_form_keeps_key_on_placeholder(tmp_path, monkeypatch):
    """api_key 为占位符时不应改动钥匙串（仅验证不抛错、其它字段照常更新）。"""
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app._apply_online_form(f"base_url=https://x/v1\nmodel=m\napi_key={app._KEY_PLACEHOLDER}")
    assert load_config().llm.online.base_url == "https://x/v1"


def test_test_connection_message_ollama_offline(app):
    """Ollama 不可达时返回友好提示（指向不存在端口）。"""
    app.cfg.llm.mode = "ollama"
    app.cfg.llm.ollama.base_url = "http://localhost:1"  # 无效端口
    msg = app.test_connection_message()
    assert "未连接" in msg or "Ollama" in msg
