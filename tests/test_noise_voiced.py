"""噪音拦截改用"语音时长"(去静音)：voiced_seconds 计量 + pipeline 不误杀真短词。"""

from __future__ import annotations

import numpy as np

from voiceinput.audio import voiced_seconds
from voiceinput.config import Config
from voiceinput.pipeline import Pipeline, _spoken_len


def test_spoken_len_excludes_punctuation():
    assert _spoken_len("我的。") == 2          # 句号不计
    assert _spoken_len("我。") == 1
    assert _spoken_len("。，！？") == 0          # 纯标点
    assert _spoken_len("今天 天气, 不错!") == 6   # 标点/空格都排除


def _tone(sec, sr=16000, amp=0.2):
    """一段恒定幅度的"有声"信号（RMS≈amp，高于默认阈值 0.036）。"""
    return np.full(int(sec * sr), amp, dtype="float32")


def _silence(sec, sr=16000):
    return np.zeros(int(sec * sr), dtype="float32")


def test_voiced_seconds_excludes_silence():
    # 0.3s 有声 + 3s 静音 → 语音时长≈0.3s（去掉静音），而非 3.3s
    audio = np.concatenate([_tone(0.3), _silence(3.0)])
    v = voiced_seconds(audio, threshold=0.036)
    assert 0.25 <= v <= 0.35, v
    # 纯静音 → 0
    assert voiced_seconds(_silence(5.0), 0.036) == 0.0


class _Inj:
    def __init__(self):
        self.text = None

    def type_text(self, t):
        self.text = t


def _run(audio, raw, cfg, speech_sec=None):
    inj = _Inj()
    p = Pipeline(cfg, inj, transcribe_fn=lambda a: raw)
    return p.run(audio, speech_sec=speech_sec), inj


def test_real_short_word_with_leading_silence_not_dropped():
    """真短词"我"(0.3s 语音)前面有 3s 静音 → 段长 3.3s，但语音足够，不应误杀。"""
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    audio = np.concatenate([_silence(3.0), _tone(0.3)])  # 段长 3.3s，语音 0.3s
    res, inj = _run(audio, "我", cfg)
    assert res.final_text == "我" and inj.text == "我"     # 0.3s ≥ 0.08s → 保留


def test_noise_hallucination_dropped():
    """底噪幻觉：长段几乎无语音(0.02s 一闪) → 判噪音跳过（final_text 置空、不注入）。"""
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    audio = np.concatenate([_silence(5.0), _tone(0.02)])  # 语音仅 0.02s < 0.08s
    res, inj = _run(audio, "我", cfg)
    assert res.raw_text == "我" and res.final_text == "" and inj.text is None


def test_punctuation_not_counted_keeps_real_word():
    """'我的。'(真发声2字)语音0.18s：句号不计字数→门槛0.14→保留(修复误杀)。"""
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    audio = np.concatenate([_silence(4.0), _tone(0.18)])   # 段长4.18s，语音0.18s
    res, inj = _run(audio, "我的。", cfg)
    assert res.final_text == "我的。" and inj.text == "我的。"


def test_punctuation_stripped_single_char_noise_dropped():
    """'我。'(真发声1字)语音0.06s：门槛0.08→仍判噪音拦截。"""
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    # 静音取 3.0s（=100×30ms 窗，窗口对齐）避免边界窗把语音时长量大
    audio = np.concatenate([_silence(3.0), _tone(0.03)])   # 语音0.03s < 0.05s
    res, inj = _run(audio, "我。", cfg)
    assert res.raw_text == "我。" and res.final_text == "" and inj.text is None


def test_speech_sec_param_preferred_over_remeasure():
    """传入 VAD 实测语音时长时优先采用它判定（修复事后重测把真语音漏算成0的误杀）。"""
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    # 整段几乎全静音，事后重测≈0；但 VAD 切段实测语音 0.25s → 应保留
    audio = np.concatenate([_silence(3.0), _tone(0.01)])
    res, inj = _run(audio, "我的。", cfg, speech_sec=0.25)
    assert res.final_text == "我的。" and inj.text == "我的。"
    # 同段，VAD 实测仅 0.03s < 0.05（2字门槛）→ 仍拦
    res2, inj2 = _run(audio, "我的。", cfg, speech_sec=0.03)
    assert res2.final_text == "" and inj2.text is None


def test_zero_threshold_disables_per_char():
    cfg = Config()
    cfg.llm.enabled = False
    cfg.postprocess.mode = "raw"
    cfg.asr.force_filter_phrases = []  # 隔离强制过滤，只测噪音判定
    cfg.vad.noise_min_voice_1char_sec = 0.0               # 1 字不拦
    audio = np.concatenate([_silence(5.0), _tone(0.01)])
    res, inj = _run(audio, "我", cfg)
    assert res.final_text == "我" and inj.text == "我"
