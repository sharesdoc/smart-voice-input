"""系统配置：枚举解析 / 恢复默认（旧文本设置 UI 已删除，相关用例随之移除）。"""

import pytest

from voiceinput.app import VoiceInputApp, _enum_parse
from voiceinput.config import Config, load_config


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    return VoiceInputApp(cfg=Config())


def test_enum_parse_accepts_zh_en_internal():
    assert _enum_parse("asr_engine", "阿里云Fun-ASR") == "dashscope"
    assert _enum_parse("asr_engine", "Aliyun Fun-ASR") == "dashscope"
    assert _enum_parse("asr_engine", "dashscope") == "dashscope"
    assert _enum_parse("bool", "开") is True
    assert _enum_parse("bool", "off") is False
    assert _enum_parse("ppmode", "不存在") is None


def test_restore_defaults(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app.cfg.asr.engine = "dashscope"
    app.cfg.postprocess.mode = "organize"
    app._restore_defaults()
    assert app.cfg.asr.engine == "whisper_local"      # 回到默认
    assert app.cfg.postprocess.mode == "polish"
    assert load_config().asr.engine == "whisper_local"
