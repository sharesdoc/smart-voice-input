"""配置加载/保存测试 (FR-11/FR-12)。"""

import json

from voiceinput.config import (
    Config,
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
