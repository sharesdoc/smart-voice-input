"""LLM 后处理测试 (FR-07/08/09)。用假 httpx client，无需真实网络。"""

from voiceinput.config import Config
from voiceinput.llm import (
    build_messages,
    needs_llm,
    postprocess,
    system_prompt_for,
)


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._data


class FakeOllamaClient:
    def __init__(self, content):
        self.content = content
        self.posted = None

    def post(self, url, json=None, headers=None):
        self.posted = {"url": url, "json": json, "headers": headers}
        return FakeResp({"message": {"content": self.content}})

    def close(self):
        pass


class FakeOnlineClient:
    def __init__(self, content):
        self.content = content
        self.posted = None

    def post(self, url, json=None, headers=None):
        self.posted = {"url": url, "json": json, "headers": headers}
        return FakeResp({"choices": [{"message": {"content": self.content}}]})

    def close(self):
        pass


class FailingClient:
    def post(self, *a, **k):
        raise RuntimeError("connection refused")

    def close(self):
        pass


def test_system_prompt_organize_mode():
    cfg = Config()
    cfg.postprocess.mode = "organize"
    prompt = system_prompt_for(cfg)
    assert "整理" in prompt or "梳理" in prompt


def test_system_prompt_english_when_language_en():
    cfg = Config()
    cfg.general.language = "en"
    cfg.postprocess.mode = "polish"
    prompt = system_prompt_for(cfg)
    assert "speech-input" in prompt or "punctuation" in prompt


def test_system_prompt_custom_template_overrides():
    cfg = Config()
    cfg.postprocess.prompt_template = "自定义模板XYZ"
    assert system_prompt_for(cfg) == "自定义模板XYZ"


def test_translate_prompt_includes_target():
    cfg = Config()
    cfg.postprocess.mode = "translate"
    cfg.postprocess.translate_target = "en"
    assert "en" in system_prompt_for(cfg)


def test_build_messages_structure():
    cfg = Config()
    msgs = build_messages(cfg, "你好世界")
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "你好世界"}


def test_needs_llm_false_for_raw():
    cfg = Config()
    cfg.postprocess.mode = "raw"
    assert needs_llm(cfg) is False


def test_needs_llm_false_when_disabled():
    cfg = Config()
    cfg.llm.enabled = False
    assert needs_llm(cfg) is False


def test_postprocess_ollama_success():
    cfg = Config()
    cfg.llm.mode = "ollama"
    cfg.postprocess.mode = "organize"
    client = FakeOllamaClient("我今天很高兴。")
    res = postprocess(cfg, "我今天很高心", client=client)
    assert res.ok is True
    assert res.text == "我今天很高兴。"
    assert client.posted["url"].endswith("/api/chat")


def test_ollama_payload_uses_conservative_generation_settings():
    cfg = Config()
    cfg.llm.mode = "ollama"
    cfg.llm.temperature = 0.0
    cfg.llm.max_output_tokens = 128
    cfg.llm.reasoning = "off"
    client = FakeOllamaClient("你好。")

    res = postprocess(cfg, "你好", client=client)

    assert res.ok is True
    payload = client.posted["json"]
    assert payload["think"] is False
    assert payload["options"]["temperature"] == 0.0
    assert payload["options"]["num_predict"] == 128


def test_postprocess_online_success():
    cfg = Config()
    cfg.llm.mode = "online"
    client = FakeOnlineClient("polished text")
    res = postprocess(cfg, "raw text", client=client)
    assert res.ok is True
    assert res.text == "polished text"
    assert client.posted["url"].endswith("/chat/completions")


def test_online_deepseek_payload_disables_thinking():
    cfg = Config()
    cfg.llm.mode = "online"
    cfg.llm.online.base_url = "https://api.deepseek.com/v1"
    cfg.llm.online.model = "deepseek-chat"
    cfg.llm.reasoning = "off"
    cfg.llm.max_output_tokens = 96
    client = FakeOnlineClient("整理后文本")

    res = postprocess(cfg, "整理前文本", client=client)

    assert res.ok is True
    payload = client.posted["json"]
    assert payload["max_tokens"] == 96
    assert payload["thinking"] == {"type": "disabled"}


def test_postprocess_strips_thinking_content():
    cfg = Config()
    cfg.llm.mode = "ollama"
    cfg.llm.strip_thinking = True
    client = FakeOllamaClient("<think>先分析一下</think>\n最终文本。")

    res = postprocess(cfg, "最终文本", client=client)

    assert res.ok is True
    assert res.text == "最终文本。"


def test_postprocess_degrades_on_error():
    """网络失败时降级为原文，ok=False（NFR-04）。"""
    cfg = Config()
    cfg.llm.mode = "ollama"
    res = postprocess(cfg, "原始文本", client=FailingClient())
    assert res.ok is False
    assert res.text == "原始文本"


def test_postprocess_empty_input():
    cfg = Config()
    res = postprocess(cfg, "   ")
    assert res.text == ""
    assert res.ok is True


def test_postprocess_raw_mode_skips_llm():
    cfg = Config()
    cfg.postprocess.mode = "raw"
    # 即使传入会失败的 client，也不会被调用
    res = postprocess(cfg, "保持原样", client=FailingClient())
    assert res.ok is True
    assert res.text == "保持原样"
