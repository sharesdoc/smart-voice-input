"""LLM 后处理：纠错 / 整理 / 翻译 (FR-07/08/09)。

两种引擎：
- Ollama 本地：HTTP POST {base_url}/api/chat (FR-08)
- OpenAI 兼容在线：/v1/chat/completions (FR-07)

设计：提示词构建 (build_messages) 为纯函数，可单测；网络调用集中在
postprocess()，通过 httpx 实现，超时与降级遵循 NFR-04（失败回退原文）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, get_api_key

# 各后处理模式的内置系统提示词（用户可在配置覆盖）。
_BUILTIN_PROMPTS: dict[str, dict[str, str]] = {
    "zh": {
        "polish": (
            "你是中文语音输入助手。请对语音识别文本做轻量加工：纠正错别字、"
            "补全标点。保持原意与原有措辞，不重组语序、不删改信息。仅输出结果文本，"
            "不要任何解释或引号。"
        ),
        "organize": (
            "你是中文语音输入整理助手。请对语音识别文本进行意图识别与逻辑梳理："
            "纠正错别字、补全标点、删除口头禅与重复冗余、必要时重组语序使语句通顺连贯。"
            "务必忠于原意，不扩写、不臆造新信息、不回答其中的问题。仅输出整理后的最终文本，"
            "不要任何解释、前后缀或引号。"
        ),
        "translate": (
            "你是翻译助手。请把下面的文本准确翻译为目标语言：{target}。"
            "仅输出译文，不要任何解释或引号。"
        ),
    },
    "en": {
        "polish": (
            "You are a speech-input assistant. Lightly fix typos and add punctuation. "
            "Keep the original wording and meaning; do not rephrase or drop information. "
            "Output only the resulting text, with no quotes or explanation."
        ),
        "organize": (
            "You are a speech-input editing assistant. Fix errors, add punctuation, "
            "remove fillers and redundancy, and reorder for fluency while staying "
            "faithful to the original meaning. Do not add new information or answer any "
            "question within. Output only the final text, no quotes or explanation."
        ),
        "translate": (
            "You are a translator. Accurately translate the following text into the "
            "target language: {target}. Output only the translation, no quotes or notes."
        ),
    },
}


@dataclass
class LlmResult:
    """后处理结果。ok=False 时 text 回退为原文（NFR-04 降级）。"""

    text: str
    ok: bool
    error: str = ""


def system_prompt_for(cfg: Config) -> str:
    """根据语言、后处理模式与用户模板，得到系统提示词。"""
    pp = cfg.postprocess
    if pp.prompt_template.strip():
        tmpl = pp.prompt_template
    else:
        lang = cfg.general.language if cfg.general.language in _BUILTIN_PROMPTS else "zh"
        lang_prompts = _BUILTIN_PROMPTS[lang]
        tmpl = lang_prompts.get(pp.mode, lang_prompts["polish"])
    if pp.mode == "translate":
        tmpl = tmpl.replace("{target}", pp.translate_target)
    return tmpl


def build_messages(cfg: Config, raw_text: str) -> list[dict[str, str]]:
    """构建 chat messages（OpenAI/Ollama 通用格式）。纯函数。"""
    return [
        {"role": "system", "content": system_prompt_for(cfg)},
        {"role": "user", "content": raw_text},
    ]


def needs_llm(cfg: Config) -> bool:
    """当前配置是否需要调用 LLM。raw 模式或关闭时不调用。"""
    if not cfg.llm.enabled or cfg.llm.mode == "off":
        return False
    if cfg.postprocess.mode == "raw":
        return False
    return True


def postprocess(cfg: Config, raw_text: str, *, client=None) -> LlmResult:
    """对原始转写文本做后处理。

    raw_text 为空或无需 LLM 时直接返回原文。任何网络/解析错误都降级为原文
    （ok=False），绝不让后处理失败阻断输入（NFR-04）。

    client: 可注入的 httpx.Client（测试用）；为 None 时内部创建。
    """
    raw_text = raw_text.strip()
    if not raw_text or not needs_llm(cfg):
        return LlmResult(text=raw_text, ok=True)

    from .logsetup import get_logger
    log = get_logger()
    try:
        if cfg.llm.mode == "ollama":
            log.info("调用LLM[本地Ollama %s] @%s 温度=%s",
                     cfg.llm.ollama.model, cfg.llm.ollama.base_url, cfg.llm.temperature)
            text = _call_ollama(cfg, raw_text, client=client)
        elif cfg.llm.mode == "online":
            log.info("调用LLM[在线 %s] @%s 温度=%s",
                     cfg.llm.online.model, cfg.llm.online.base_url, cfg.llm.temperature)
            text = _call_online(cfg, raw_text, client=client)
        else:
            return LlmResult(text=raw_text, ok=True)
        text = (text or "").strip()
        if not text:
            return LlmResult(text=raw_text, ok=False, error="空响应")
        return LlmResult(text=text, ok=True)
    except Exception as exc:  # 降级保底
        return LlmResult(text=raw_text, ok=False, error=str(exc))


def _new_client(timeout: float):
    import httpx  # 懒加载

    return httpx.Client(timeout=timeout)


def _call_ollama(cfg: Config, raw_text: str, *, client=None) -> str:
    url = cfg.llm.ollama.base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": cfg.llm.ollama.model,
        "messages": build_messages(cfg, raw_text),
        "stream": False,
        "options": {"temperature": cfg.llm.temperature},
    }
    owns = client is None
    client = client or _new_client(cfg.llm.timeout_sec)
    try:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
    finally:
        if owns:
            client.close()


def _call_online(cfg: Config, raw_text: str, *, client=None) -> str:
    url = cfg.llm.online.base_url.rstrip("/") + "/chat/completions"
    api_key = get_api_key() or ""
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": cfg.llm.online.model,
        "messages": build_messages(cfg, raw_text),
        "temperature": cfg.llm.temperature,
        "stream": False,
    }
    owns = client is None
    client = client or _new_client(cfg.llm.timeout_sec)
    try:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    finally:
        if owns:
            client.close()


def list_ollama_models(cfg: Config, *, client=None) -> list[str]:
    """列出本地 Ollama 已安装模型（设置界面用）。失败返回空列表。"""
    try:
        url = cfg.llm.ollama.base_url.rstrip("/") + "/api/tags"
        owns = client is None
        client = client or _new_client(5)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        finally:
            if owns:
                client.close()
    except Exception:
        return []
