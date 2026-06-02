"""流程编排测试 —— 用假注入器记录操作序列（整理后一次性注入）。"""

from voiceinput.config import Config
from voiceinput.llm import LlmResult
from voiceinput.pipeline import Pipeline


class FakeInjector:
    """记录注入操作，模拟输入框内容。"""

    def __init__(self):
        self.buffer = ""        # 模拟输入框文本
        self.ops = []           # 操作日志

    def type_text(self, text):
        self.buffer += text
        self.ops.append(("type", text))


def make_pipeline(cfg, injector, raw_text, refined_text=None, llm_ok=True):
    """构造 pipeline：transcribe 固定返回 raw_text；LLM 返回 refined_text。"""
    def transcribe(_audio):
        return raw_text

    def fake_pp(_cfg, text):
        return LlmResult(text=refined_text if refined_text is not None else text,
                         ok=llm_ok)

    return Pipeline(cfg, injector, transcribe, postprocess_fn=fake_pp)


def test_raw_mode_injects_once():
    cfg = Config()
    cfg.postprocess.mode = "raw"
    inj = FakeInjector()
    p = make_pipeline(cfg, inj, "原始文本")
    res = p.run(object())
    assert res.final_text == "原始文本"
    assert res.rewritten is False
    assert inj.buffer == "原始文本"
    assert [op[0] for op in inj.ops] == ["type"]  # 只注入一次


def test_organize_injects_final_only():
    """整理后一次注入，无即时预览、无回删。"""
    cfg = Config()
    cfg.postprocess.mode = "organize"
    inj = FakeInjector()
    p = make_pipeline(cfg, inj, "口语化的原始内容", "整理好的书面文本")
    res = p.run(object())
    assert res.rewritten is False
    assert res.final_text == "整理好的书面文本"
    assert inj.buffer == "整理好的书面文本"
    assert [op[0] for op in inj.ops] == ["type"]  # 仅一次注入，无删除


def test_empty_transcription_does_nothing():
    cfg = Config()
    inj = FakeInjector()
    p = make_pipeline(cfg, inj, "")
    res = p.run(object())
    assert res.final_text == ""
    assert inj.ops == []


def test_llm_failure_keeps_raw():
    """LLM 失败降级：用原始文本一次注入（NFR-04）。"""
    cfg = Config()
    cfg.postprocess.mode = "organize"
    inj = FakeInjector()
    p = make_pipeline(cfg, inj, "原始内容", refined_text="原始内容", llm_ok=False)
    res = p.run(object())
    assert res.final_text == "原始内容"
    assert res.rewritten is False
    assert inj.buffer == "原始内容"


def test_state_callbacks_emitted():
    cfg = Config()
    cfg.postprocess.mode = "organize"
    inj = FakeInjector()
    states = []
    p = make_pipeline(cfg, inj, "口语原始内容很长一段", "整理后的书面内容也不短")
    p.on_state = lambda s: states.append(s)
    p.run(object())
    assert "TRANSCRIBING" in states
    assert "REFINING" in states      # organize 调 LLM
    assert "INJECTING" in states
    assert states[-1] == "IDLE"
    assert "REWRITING" not in states  # 已无动态重写
