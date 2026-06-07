"""配置加载/保存测试 (FR-11/FR-12)。"""

import json

from voiceinput.config import (
    Config,
    DEFAULT_OLLAMA_MODEL,
    config_path,
    load_config,
    save_config,
)


def test_default_config_values():
    cfg = Config()
    assert cfg.general.language == "zh"
    assert cfg.hotkey.trigger == "double_command"
    assert cfg.hotkey.double_tap_ms == 300
    assert cfg.asr.engine == "whisper_local"
    assert cfg.asr.force_filter_phrases == [
        "我", "我的", "我是", "是的", "Yeah", "字幕by索兰娅", "嗯", "嗯嗯"
    ]
    assert cfg.llm.ollama.model == DEFAULT_OLLAMA_MODEL
    assert DEFAULT_OLLAMA_MODEL == "qwen2.5:7b-instruct-q4_K_M"
    assert cfg.postprocess.mode == "polish"


def test_roundtrip_save_load(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    cfg = Config()
    cfg.postprocess.mode = "organize"
    cfg.llm.ollama.model = "llama3.1:8b"
    cfg.hotkey.double_tap_ms = 250
    save_config(cfg)

    loaded = load_config()
    assert loaded.postprocess.mode == "organize"
    assert loaded.llm.ollama.model == "llama3.1:8b"
    assert loaded.hotkey.double_tap_ms == 250


def test_load_missing_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path / "nope"))
    cfg = load_config()
    assert cfg.postprocess.mode == "polish"  # 默认值


def test_load_corrupt_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text("{ not valid json ", encoding="utf-8")
    cfg = load_config()  # 不应抛异常
    assert isinstance(cfg, Config)
    assert cfg.llm.mode == "ollama"


def test_partial_config_fills_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        json.dumps({"postprocess": {"mode": "translate"}}), encoding="utf-8"
    )
    cfg = load_config()
    assert cfg.postprocess.mode == "translate"
    assert cfg.general.language == "zh"  # 缺失项回退默认
    assert cfg.llm.ollama.base_url == "http://localhost:11434"


def test_vad_and_online_asr_defaults():
    cfg = Config()
    assert cfg.vad.enabled is True
    assert cfg.vad.silence_sec == 1.0
    assert cfg.asr.online_model == "whisper-1"


def test_vad_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    cfg = Config()
    cfg.vad.enabled = False
    cfg.vad.silence_sec = 2.0
    cfg.asr.engine = "online"
    save_config(cfg)
    loaded = load_config()
    assert loaded.vad.enabled is False
    assert loaded.vad.silence_sec == 2.0
    assert loaded.asr.engine == "online"


def test_api_key_not_in_config_file(tmp_path, monkeypatch):
    """API Key 不得明文写入配置文件 (FR-12/NFR-06)。"""
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    cfg = Config()
    save_config(cfg)
    raw = config_path().read_text(encoding="utf-8")
    assert "api_key" not in raw.lower()


# ---- 钥匙串相关函数测试 (FR-12)：用假 keyring 模块注入，避免依赖系统钥匙串 ----


class _FakeKeyring:
    """内存版 keyring，模拟 set/get/delete_password。"""

    def __init__(self):
        self.store = {}

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        del self.store[(service, account)]


class _BrokenKeyring:
    """所有操作均抛异常，模拟 keyring 不可用。"""

    def set_password(self, *a, **k):
        raise RuntimeError("no backend")

    def get_password(self, *a, **k):
        raise RuntimeError("no backend")

    def delete_password(self, *a, **k):
        raise RuntimeError("no backend")


def _inject_keyring(monkeypatch, fake):
    import sys

    monkeypatch.setitem(sys.modules, "keyring", fake)


def test_keyring_success_paths(monkeypatch):
    """钥匙串可用时：在线/DashScope Key 的存取删与来源解析全链路。"""
    import voiceinput.config as cfg

    fake = _FakeKeyring()
    _inject_keyring(monkeypatch, fake)
    # 清除环境变量，确保走 keyring 分支
    monkeypatch.delenv("VOICEINPUT_ONLINE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    # 在线 API Key：存 → 读 → 删 → 读空
    assert cfg.set_api_key("online-key") is True
    assert cfg.get_api_key() == "online-key"
    assert cfg.delete_api_key() is True
    assert cfg.get_api_key() is None

    # DashScope Key：存 → 读 → 按来源解析
    assert cfg.set_dashscope_key("ds-key") is True
    assert cfg.get_dashscope_key() == "ds-key"
    assert cfg.resolve_dashscope_key("manual") == "ds-key"


def test_get_api_key_env_takes_priority(monkeypatch):
    """环境变量优先于钥匙串（便于 CI/临时使用）。"""
    import voiceinput.config as cfg

    _inject_keyring(monkeypatch, _FakeKeyring())
    monkeypatch.setenv("VOICEINPUT_ONLINE_API_KEY", "env-key")
    assert cfg.get_api_key() == "env-key"


def test_resolve_dashscope_key_env_source(monkeypatch):
    """非 manual 来源：从环境变量解析 DashScope Key。"""
    import voiceinput.config as cfg

    monkeypatch.setenv("DASHSCOPE_API_KEY", "ds-env")
    assert cfg.resolve_dashscope_key("env") == "ds-env"


def test_keyring_failure_paths(monkeypatch):
    """钥匙串不可用时：各函数安全降级为 False/None，不抛异常。"""
    import voiceinput.config as cfg

    _inject_keyring(monkeypatch, _BrokenKeyring())
    monkeypatch.delenv("VOICEINPUT_ONLINE_API_KEY", raising=False)

    assert cfg.set_api_key("k") is False
    assert cfg.set_dashscope_key("k") is False
    assert cfg.get_dashscope_key() is None
    assert cfg.delete_api_key() is False
    assert cfg.get_api_key() is None
