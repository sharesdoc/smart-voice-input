"""统一系统配置页测试：渲染 / 解析往返 / 恢复默认 / 精简菜单。"""

import pytest

from voiceinput.app import VoiceInputApp, _enum_parse
from voiceinput.config import Config, load_config


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    return VoiceInputApp(cfg=Config())


def test_settings_text_has_about_and_groups(app):
    txt = app._settings_text()
    assert "VoiceInput" in txt and "v" in txt        # 关于：名称/版本
    assert "当前语音识别" in txt and "当前大模型" in txt  # 当前AI服务
    assert "语音识别引擎 =" in txt and "后处理模式 =" in txt


def test_settings_roundtrip(app, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    txt = app._settings_text()
    edited = (txt
              .replace("语音识别引擎 = 本地Whisper(faster-whisper)",
                       "语音识别引擎 = 阿里云Fun-ASR")
              .replace("后处理模式 = 智能纠错润色", "后处理模式 = 纯转写")
              .replace("连续听写 = 开", "连续听写 = 关")
              .replace("停顿秒数 = 1.0", "停顿秒数 = 0.6"))
    app._apply_settings_text(edited)
    cfg = load_config()
    assert cfg.asr.engine == "dashscope"
    assert cfg.postprocess.mode == "raw"
    assert cfg.general.continuous_dictation is False
    assert cfg.vad.silence_sec == 0.6


def test_settings_ignores_unknown_and_comments(app):
    app._apply_settings_text("# 注释\n乱七八糟\n语言 = 英文\n")
    assert app.cfg.general.language == "en"


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
