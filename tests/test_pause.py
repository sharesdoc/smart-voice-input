"""停顿检测时长设置测试 (FR-04 可配置)。"""

import pytest

from voiceinput.app import VoiceInputApp, parse_pause_seconds
from voiceinput.config import Config, load_config


@pytest.mark.parametrize("text,expected", [
    ("0.8", 0.8),
    ("1", 1.0),
    ("1.5s", 1.5),
    ("800ms", 0.8),
    ("500", 0.5),       # 无单位且≥20 → 毫秒
    ("0.5秒", 0.5),     # 中文“秒”
    (" 1.0 ", 1.0),
])
def test_parse_pause_valid(text, expected):
    assert parse_pause_seconds(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "ms", None])
def test_parse_pause_invalid(text):
    assert parse_pause_seconds(text) is None


def test_parse_pause_clamped():
    assert parse_pause_seconds("0.01") == 0.2   # 秒，低于下限 → 0.2
    assert parse_pause_seconds("99") == 0.2     # 无单位≥20→毫秒0.099→clamp下限0.2


def test_parse_pause_large_seconds_clamped():
    assert parse_pause_seconds("10s") == 5.0    # 显式秒，超上限被 clamp 到 5.0
    assert parse_pause_seconds("9000ms") == 5.0  # 9 秒 → clamp 5.0


def test_apply_vad_silence_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app.apply_vad_silence(0.6)
    assert app.cfg.vad.silence_sec == 0.6
    assert load_config().vad.silence_sec == 0.6


def test_apply_vad_silence_clamps(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app.apply_vad_silence(99)
    assert app.cfg.vad.silence_sec == 5.0
    app.apply_vad_silence(0.01)
    assert app.cfg.vad.silence_sec == 0.2
