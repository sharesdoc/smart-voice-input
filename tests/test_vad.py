"""VAD 静音自动断句测试 (FR-04)。"""

import numpy as np

from voiceinput.audio import SilenceDetector, rms


def _speech(seconds, sr=16000, amp=0.2):
    return (np.random.RandomState(0).randn(int(seconds * sr)) * amp).astype("float32")


def _silence(seconds, sr=16000):
    return np.zeros(int(seconds * sr), dtype="float32")


def test_rms_zero_for_silence():
    assert rms(_silence(0.1)) == 0.0


def test_rms_positive_for_speech():
    assert rms(_speech(0.1)) > 0.01


def test_no_stop_on_leading_silence():
    """开头就静音不应立即结束（需先有语音）。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3)
    assert d.feed(_silence(2.0)) is False


def test_stop_after_speech_then_silence():
    """语音后持续静音超过阈值 → 结束。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3)
    assert d.feed(_speech(0.5)) is False      # 语音
    assert d.feed(_silence(0.5)) is False     # 静音 0.5s < 1.0s
    assert d.feed(_silence(0.6)) is True       # 累计 1.1s >= 1.0s → 结束


def test_silence_reset_by_speech():
    """中途又说话应重置静音计时。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3)
    d.feed(_speech(0.5))
    d.feed(_silence(0.8))      # 静音 0.8s
    assert d.feed(_speech(0.2)) is False  # 又说话，重置
    assert d.feed(_silence(0.8)) is False  # 0.8s < 1.0s，不结束


def test_min_speech_gate():
    """语音不足 min_speech_sec 时不触发结束。"""
    d = SilenceDetector(silence_sec=0.5, min_speech_sec=1.0)
    d.feed(_speech(0.2))       # 语音仅 0.2s < 1.0s
    assert d.feed(_silence(2.0)) is False  # 即使长静音也不结束


def test_reset_clears_state():
    d = SilenceDetector(silence_sec=0.5, min_speech_sec=0.1)
    d.feed(_speech(0.3))
    d.reset()
    assert d.feed(_silence(1.0)) is False  # 重置后无语音记录
