"""SenseVoice 纯标点过滤测试（修复：静音段莫名输出一个句号）。

只测纯函数 _is_meaningless，不加载 funasr/torch。
"""

from voiceinput.asr import _is_meaningless


def test_lone_period_is_meaningless():
    assert _is_meaningless("。") is True          # 正是要消除的"莫名句号"


def test_only_punctuation_is_meaningless():
    for s in ("，。", " 。 ", "！？", "…", "、", "。。。", "  ", ""):
        assert _is_meaningless(s) is True, s


def test_real_text_with_period_is_kept():
    # 有真实文字(哪怕带句号)不算无意义 → 句号保留
    for s in ("你好。", "今天天气不错。", "hello.", "测试123。", "好"):
        assert _is_meaningless(s) is False, s


def test_none_is_meaningless():
    assert _is_meaningless(None) is True
