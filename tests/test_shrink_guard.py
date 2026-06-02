"""异常偏短护栏测试（防 LLM 把长段整理成一小句导致内容丢失）。"""

from voiceinput.config import Config
from voiceinput.pipeline import Pipeline, _drastic_shrink
from voiceinput.llm import LlmResult


def test_drastic_shrink_true_for_truncation():
    raw = "今天我们开会讨论了三个议题，分别是预算、排期和人手安排。"
    refined = "人手安排。"                 # LLM 只剩最后一句
    assert _drastic_shrink(raw, refined) is True


def test_drastic_shrink_false_for_normal_polish():
    raw = "今天天气不错我们出去走走吧"
    refined = "今天天气不错，我们出去走走吧。"   # 仅加标点，长度相近
    assert _drastic_shrink(raw, refined) is False


def test_drastic_shrink_false_for_short_raw():
    # 原文很短时不启用(避免误伤正常短句)
    assert _drastic_shrink("你好", "好") is False


def test_drastic_shrink_empty_refined():
    assert _drastic_shrink("一段比较长的原始语音识别文本内容", "") is True


class SpyInjector:
    def __init__(self):
        self.typed = []

    def type_text(self, text):
        self.typed.append(text)


def _cfg():
    cfg = Config()
    cfg.postprocess.mode = "polish"
    cfg.llm.mode = "ollama"
    return cfg


def test_keeps_raw_when_llm_truncates():
    """LLM 返回异常偏短 → 改用原文注入，不注入残缺结果。"""
    raw = "今天我们开会讨论了三个议题，分别是预算、排期和人手安排。"
    inj = SpyInjector()
    p = Pipeline(
        cfg=_cfg(), injector=inj,
        transcribe_fn=lambda a: raw,
        postprocess_fn=lambda c, t: LlmResult(text="人手安排。", ok=True),
    )
    r = p.run([0.0] * 1600)
    assert inj.typed == [raw]            # 一次注入原文，不是残缺的"人手安排。"
    assert r.final_text == raw


def test_normal_polish_still_injected():
    """正常长度的整理结果一次注入。"""
    raw = "今天天气不错我们出去走走吧"
    refined = "今天天气不错，我们出去走走吧。"
    inj = SpyInjector()
    p = Pipeline(
        cfg=_cfg(), injector=inj,
        transcribe_fn=lambda a: raw,
        postprocess_fn=lambda c, t: LlmResult(text=refined, ok=True),
    )
    r = p.run([0.0] * 1600)
    assert inj.typed == [refined]       # 一次注入整理版
    assert r.final_text == refined
