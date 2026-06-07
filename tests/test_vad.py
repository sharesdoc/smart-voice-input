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


def test_short_tail_speech_still_stops():
    """最跟手：说完几个字（语音不足 min_speech_sec）后持续静音，仍应结束。

    回归 X-101：旧逻辑要求累计语音 >= min_speech_sec 才置 _had_speech，
    短尾句（如 0.2s）永远不切段，卡在缓冲里，必须再开口说话才被一起带出
    （并导致前后两遍重复输出）。修复后只要出现过有效语音，静音够久即结束。
    """
    d = SilenceDetector(silence_sec=0.5, min_speech_sec=1.0)
    assert d.feed(_speech(0.2)) is False   # 语音仅 0.2s < 1.0s 门槛
    assert d.feed(_silence(2.0)) is True   # 持续静音 → 应切段输出，不再卡死


def test_no_speech_never_stops():
    """从未检测到任何有效语音时，无论静音多久都不结束（防纯底噪误触发）。"""
    d = SilenceDetector(silence_sec=0.5, min_speech_sec=1.0)
    assert d.feed(_silence(3.0)) is False


def test_reset_clears_state():
    d = SilenceDetector(silence_sec=0.5, min_speech_sec=0.1)
    d.feed(_speech(0.3))
    d.reset()
    assert d.feed(_silence(1.0)) is False  # 重置后无语音记录


# ---- 软封顶：渐进式自适应切段 (X-103) ----
# 放录音/少停顿场景：单段过长时逐步放宽"所需静音时长"，就近找微停顿切段，
# 避免整段无限累积（在线引擎超时、本地内存涨），同时尽量切在自然停顿不伤语义。


def test_soft_cap_disabled_keeps_base_behavior():
    """soft_cap_sec=0（默认禁用）时行为与原始一致：仅按 silence_sec 切。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=0.0, hard_cap_sec=0.0)
    d.feed(_speech(0.5))
    assert d.feed(_silence(0.7)) is False   # 0.7 < 1.0，未放宽则不切


def test_below_soft_cap_uses_full_silence():
    """未达 soft_cap 前，所需静音仍是完整 silence_sec，短停顿不切。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=2.0, hard_cap_sec=4.0)
    d.feed(_speech(0.5))                     # 段总时长 0.5s « soft_cap
    assert d.feed(_silence(0.7)) is False    # 0.7 < 1.0，不切


def test_over_soft_cap_relaxes_silence():
    """超过 soft_cap 后立刻减半：第一阶(≥2s) → 静音要求 0.5s。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=2.0, hard_cap_sec=24.0,
                        soft_cap_step_sec=10.0)
    # 段长到 8s：steps=1+int((8-2)/10)=1, req=1.0/2=0.5s
    assert d.feed(_speech(8.0)) is False      # 仍在说话，不切
    assert d.feed(_silence(0.3)) is False     # 0.3 < 0.5，不切
    assert d.feed(_silence(0.3)) is True      # 累计 0.6s ≥ 0.5s → 切

def test_second_step_halves_to_quarter():
    """第二阶（≥12s）：静音要求再减半 → 0.25s。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=2.0, hard_cap_sec=24.0,
                        soft_cap_step_sec=10.0)
    # 段长到 18s：steps=1+int((18-2)/10)=2, req=0.25s
    assert d.feed(_speech(18.0)) is False
    assert d.feed(_silence(0.15)) is False    # 0.15 < 0.25
    assert d.feed(_silence(0.15)) is True     # 累计 0.3 ≥ 0.25 → 切


def test_hard_cap_forces_cut_without_pause():
    """到达 hard_cap 仍无任何可用停顿（持续发声）→ 硬切兜底。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=2.0, hard_cap_sec=4.0)
    assert d.feed(_speech(4.5)) is True      # 段总时长 ≥ hard_cap → 强制切


def test_hard_cap_triggers_on_silence_to_prevent_oom():
    """纯静音超 hard_cap 也强制切——防止 _frames 无限膨胀 OOM。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=2.0, hard_cap_sec=4.0)
    assert d.feed(_silence(5.0)) is True   # 硬切触发，防止内存溢出


def test_only_hard_cap_without_soft_is_disabled():
    """只设 hard_cap 不设 soft_cap（soft<=0）时软封顶整体禁用，硬切不单独触发。

    审查整改 [1]：避免"只设其一"导致硬切单独生效的歧义。
    """
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=0.0, hard_cap_sec=4.0)
    assert d.feed(_speech(5.0)) is False   # 超 hard_cap 但软封顶未启用 → 不硬切
    assert d.feed(_silence(1.0)) is True   # 仍按正常 silence_sec=1.0 切


def test_hard_le_soft_is_disabled():
    """hard_cap <= soft_cap 的非法组合视为禁用，退化为纯 silence_sec。"""
    d = SilenceDetector(silence_sec=1.0, min_speech_sec=0.3,
                        soft_cap_sec=5.0, hard_cap_sec=3.0)
    assert d.feed(_speech(6.0)) is False   # 配置非法 → 不硬切
    assert d.feed(_silence(0.5)) is False  # 未放宽，0.5 < 1.0 不切
