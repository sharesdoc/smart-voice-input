"""本地 Whisper 语音识别封装 (FR-05)。

使用 faster-whisper（CTranslate2），跨架构（arm64/x86_64）可用。
模型懒加载（首次需下载），按需选择计算后端。
"""

from __future__ import annotations

import platform


def _pick_compute(setting: str) -> str:
    """根据配置与平台选择 CTranslate2 计算类型。

    faster-whisper 在 Apple Silicon 上走 CPU(int8) 已足够快；Metal 由底层处理。
    """
    if setting and setting not in ("auto", "metal"):
        return setting
    # int8 在 CPU 上速度/内存均衡，跨架构通用
    return "int8"


# 中文默认偏置提示词：Whisper 对中文常输出繁体，此提示词显著提升简体输出比例。
_ZH_SIMPLIFIED_PROMPT = "以下是简体中文普通话的句子。"

# Whisper 在静音/噪声段常见的"幻觉"话术(YouTube字幕训练遗留)，命中即丢弃。
_HALLUCINATION_MARKERS = (
    "请不吝点赞", "点赞", "订阅", "转发", "打赏", "明镜", "点点栏目",
    "字幕", "感谢观看", "谢谢观看", "謝謝觀看", "关注我", "下集再见",
    "Amara", "未经允许", "版权所有",
)


def _is_meaningless(text: str) -> bool:
    """文本是否不含任何"文字"(字母/数字/CJK)，即只剩标点/空白。

    用于过滤 SenseVoice 在静音/噪声段输出的孤立标点(如只有一个"。")：
    完全没说话时不应莫名其妙地注入一个句号。有真实文字时(哪怕带句号)不算无意义。
    """
    t = (text or "").strip()
    if not t:
        return True
    # isalnum() 对中文/日文/字母/数字返回 True，对标点/符号返回 False
    return not any(ch.isalnum() for ch in t)


def _dehallucinate(text: str) -> str:
    """过滤 Whisper 幻觉：重复 token 死循环 + 已知字幕/打赏话术。命中返回空串。"""
    t = (text or "").strip()
    if not t:
        return ""
    # 1) 极端重复：整体去重后字符种类极少而长度很长（如 "B3B3B3…"）
    compact = t.replace(" ", "")
    if len(compact) >= 12 and len(set(compact)) <= 4:
        return ""
    # 2) 短循环节重复（周期 1~4 的字符串重复 ≥6 次）
    for k in (1, 2, 3, 4):
        if len(compact) >= k * 6:
            unit = compact[:k]
            if unit * (len(compact) // k) == compact[:k * (len(compact) // k)] \
                    and len(compact) // k >= 6:
                return ""
    # 3) 已知字幕站/打赏类幻觉话术：命中 ≥2 个标记，或含强标记
    hits = sum(1 for m in _HALLUCINATION_MARKERS if m in t)
    strong = ("请不吝点赞" in t or "打赏支持" in t or "明镜与点点" in t
              or "Amara" in t)
    if strong or hits >= 2:
        return ""
    return t


class WhisperASR:
    """本地 Whisper 识别器。模型懒加载。"""

    def __init__(self, model_size: str = "small", compute: str = "auto",
                 language: str = "zh", initial_prompt: str | None = None) -> None:
        self.model_size = model_size
        self.compute = _pick_compute(compute)
        self.language = language
        # 中文且未自定义时，使用简体偏置提示词（FR：默认简体中文）
        if initial_prompt is None and language == "zh":
            initial_prompt = _ZH_SIMPLIFIED_PROMPT
        self.initial_prompt = initial_prompt
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # 懒加载

            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type=self.compute,
            )
        return self._model

    def transcribe(self, audio) -> str:
        """把 float32 numpy 音频转写为文本。空音频返回空串。"""
        if audio is None or len(audio) == 0:
            return ""
        model = self._ensure_model()
        segments, _info = model.transcribe(
            audio,
            language=None if self.language == "auto" else self.language,
            beam_size=5,
            initial_prompt=self.initial_prompt,
            # 防幻觉：Silero VAD 去静音 + 不跨窗条件 + 静音/压缩比阈值 + 温度0
            vad_filter=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            temperature=0.0,
        )
        return _dehallucinate("".join(seg.text for seg in segments).strip())


class OnlineASR:
    """在线语音识别 (FR-06)，OpenAI 兼容 /audio/transcriptions。

    把 float32 numpy 音频编码为 WAV，multipart 上传。失败抛异常由上层降级。
    """

    def __init__(self, base_url: str, model: str = "whisper-1",
                 language: str = "zh", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.language = language
        self.timeout = timeout

    def _encode_wav(self, audio, sample_rate: int = 16000) -> bytes:
        import io
        import wave

        import numpy as np

        pcm16 = (np.clip(np.asarray(audio, dtype="float32"), -1.0, 1.0)
                 * 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def transcribe(self, audio, *, client=None) -> str:
        if audio is None or len(audio) == 0:
            return ""
        from .config import get_api_key

        wav = self._encode_wav(audio)
        url = self.base_url + "/audio/transcriptions"
        headers = {"Authorization": f"Bearer {get_api_key() or ''}"}
        data = {"model": self.model}
        if self.language and self.language != "auto":
            data["language"] = self.language
        files = {"file": ("audio.wav", wav, "audio/wav")}

        owns = client is None
        if client is None:
            import httpx
            client = httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(url, headers=headers, data=data, files=files)
            resp.raise_for_status()
            return (resp.json().get("text") or "").strip()
        finally:
            if owns:
                client.close()


class MlxWhisperASR:
    """MLX Whisper 识别器（Apple Silicon MLX 加速，速度远超 CPU/faster-whisper）。

    依赖 mlx-whisper（懒加载）。模型为 HuggingFace repo（如 large-v3-turbo）。
    中文默认用简体偏置提示词。首次需下载模型。
    """

    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo",
                 language: str = "zh", initial_prompt: str | None = None) -> None:
        self.model = model
        self.language = language
        if initial_prompt is None and language == "zh":
            initial_prompt = _ZH_SIMPLIFIED_PROMPT
        self.initial_prompt = initial_prompt
        self._loaded = False

    def _ensure_model(self):
        """预加载模型（供启动预热）。用极短静音跑一次以触发下载+加载。"""
        if self._loaded:
            return
        import mlx_whisper  # 懒加载
        import numpy as np

        mlx_whisper.transcribe(
            np.zeros(1600, dtype="float32"), path_or_hf_repo=self.model)
        self._loaded = True

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) == 0:
            return ""
        import mlx_whisper  # 懒加载
        import numpy as np

        kwargs = {
            "path_or_hf_repo": self.model,
            # 防幻觉：不跨窗条件(避免重复死循环) + 静音/压缩比/概率阈值 + 温度0
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.6,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "temperature": 0.0,
        }
        if self.language and self.language != "auto":
            kwargs["language"] = self.language
        if self.initial_prompt:
            kwargs["initial_prompt"] = self.initial_prompt
        res = mlx_whisper.transcribe(np.asarray(audio, dtype="float32"), **kwargs)
        self._loaded = True
        return _dehallucinate((res.get("text") or "").strip())


class SenseVoiceASR:
    """本地 SenseVoice 识别器 (FunAudioLLM)：非自回归、极快、中文强、自带标点。

    依赖 funasr + torch（懒加载）。Apple Silicon 自动用 MPS 加速。
    实测预热后 ~70x 实时；首次需加载模型（约 900MB）。
    """

    # SenseVoice 支持的语言码
    _LANGS = {"zh", "en", "yue", "ja", "ko", "auto"}

    def __init__(self, model: str = "FunAudioLLM/SenseVoiceSmall",
                 language: str = "zh", device: str = "auto",
                 hub: str = "hf") -> None:
        self.model_name = model
        self.language = language if language in self._LANGS else "auto"
        self.device = device
        self.hub = hub
        self._model = None

    def _pick_device(self) -> str:
        if self.device and self.device != "auto":
            return self.device
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _ensure_model(self):
        if self._model is None:
            from funasr import AutoModel  # 懒加载

            self._model = AutoModel(
                model=self.model_name,
                hub=self.hub,
                device=self._pick_device(),
                disable_update=True,
                log_level="ERROR",
            )
        return self._model

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) == 0:
            return ""
        model = self._ensure_model()
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        res = model.generate(input=audio, language=self.language, use_itn=True)
        if not res:
            return ""
        text = rich_transcription_postprocess(res[0]["text"]).strip()
        # 静音/噪声段 SenseVoice 常只输出一个标点(如"。")：纯标点视为无内容，不注入
        if _is_meaningless(text):
            return ""
        return text


class DashScopeASR:
    """阿里云 DashScope Fun-ASR 在线识别 (paraformer-realtime-v2)。

    自带 ITN（数字/日期正规化）+ 语义标点；用环境变量 DASHSCOPE_API_KEY。
    适合无本地模型、要标点齐全的场景。把音频段编码为 16k WAV 同步调用。
    """

    _LANG_HINTS = {"zh": ["zh"], "en": ["en"]}

    def __init__(self, model: str = "paraformer-realtime-v2",
                 language: str = "zh", key_source: str = "env") -> None:
        self.model = model
        self.language = language
        self.key_source = key_source  # env | manual

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) == 0:
            return ""
        import os
        import tempfile
        import wave

        import numpy as np

        import dashscope
        from dashscope.audio.asr import Recognition

        from .config import resolve_dashscope_key

        key = resolve_dashscope_key(self.key_source)
        if key:
            dashscope.api_key = key

        pcm16 = (np.clip(np.asarray(audio, dtype="float32"), -1.0, 1.0)
                 * 32767).astype("<i2")
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm16.tobytes())

            # 参考 FunASR：在 ASR 层就开启语义标点 + 口头禅过滤(去"嗯/那个"等)，
            # 输出更干净，连 LLM 都不调也通顺。
            kwargs = {
                "semantic_punctuation_enabled": True,
                "disfluency_removal_enabled": True,
            }
            hints = self._LANG_HINTS.get(self.language)
            if hints:
                kwargs["language_hints"] = hints
            rec = Recognition(model=self.model, format="wav",
                              sample_rate=16000, callback=None, **kwargs)
            res = rec.call(path)
            if getattr(res, "status_code", 200) != 200:
                raise RuntimeError(
                    f"DashScope ASR 失败: {getattr(res, 'message', 'unknown')}")
            sentences = res.get_sentence() or []
            if not isinstance(sentences, list):
                return ""
            return "".join(s.get("text", "") for s in sentences).strip()
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass


def make_asr(cfg):
    """根据配置创建 ASR 引擎 (FR-05/FR-06)。"""
    from .logsetup import get_logger
    log = get_logger()
    if cfg.asr.engine == "dashscope":
        log.info("创建 ASR: 阿里云Fun-ASR model=%s key来源=%s 语言=%s",
                 cfg.asr.dashscope_model, cfg.asr.dashscope_key_source,
                 cfg.general.language)
        return DashScopeASR(model=cfg.asr.dashscope_model,
                            language=cfg.general.language,
                            key_source=cfg.asr.dashscope_key_source)
    if cfg.asr.engine == "online":
        log.info("创建 ASR: 在线 base=%s model=%s 语言=%s",
                 cfg.asr.online_base_url, cfg.asr.online_model, cfg.general.language)
        return OnlineASR(
            base_url=cfg.asr.online_base_url,
            model=cfg.asr.online_model,
            language=cfg.general.language,
        )
    if cfg.asr.engine == "sensevoice":
        log.info("创建 ASR: 本地SenseVoice model=%s 语言=%s",
                 cfg.asr.sensevoice_model, cfg.general.language)
        return SenseVoiceASR(
            model=cfg.asr.sensevoice_model,
            language=cfg.general.language,
        )
    if cfg.asr.engine == "mlx_whisper":
        log.info("创建 ASR: 本地MLX Whisper model=%s 语言=%s",
                 cfg.asr.mlx_model, cfg.general.language)
        return MlxWhisperASR(
            model=cfg.asr.mlx_model,
            language=cfg.general.language,
            initial_prompt=cfg.asr.initial_prompt or None,
        )
    log.info("创建 ASR: 本地Whisper model=%s compute=%s 语言=%s",
             cfg.asr.whisper_model, cfg.asr.compute, cfg.general.language)
    return WhisperASR(
        model_size=cfg.asr.whisper_model,
        compute=cfg.asr.compute,
        language=cfg.general.language,
        initial_prompt=cfg.asr.initial_prompt or None,
    )
