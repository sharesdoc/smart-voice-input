"""语音输入流程编排：ASR → LLM 整理 → 一次性注入。

把"识别→整理→注入"的业务流程与具体的录音/GUI 解耦，依赖通过构造注入，便于单元测试。
交互方式：整理完成后一次性注入（不做实时回删重写，跨 App 最稳、无残留）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import llm as llm_mod
from .config import Config
from .logsetup import get_logger

_log = get_logger()


def _clip(text: str, n: int = 200) -> str:
    """日志里截断长文本。"""
    text = text or ""
    return text if len(text) <= n else text[:n] + "…"


def _drastic_shrink(raw: str, refined: str, *, min_len: int = 12,
                    ratio: float = 0.5) -> bool:
    """整理结果是否相对原文"异常偏短"(疑似 LLM 截断/抽风)。

    用于防止 LLM 把一大段原文整理成一小句导致内容丢失：原文较长(≥min_len)
    且整理结果短于其 ratio 比例时判为异常，调用方据此改用原文。
    **不适用于翻译模式**(译文长度与原文无可比性)，由调用方按 mode 排除。
    """
    r = (raw or "").strip()
    f = (refined or "").strip()
    if len(r) < min_len:
        return False
    return len(f) < ratio * len(r)


@dataclass
class PipelineResult:
    raw_text: str           # ASR 原始文本
    final_text: str         # 最终落入输入框的文本
    rewritten: bool         # 是否发生了回删替换
    llm_ok: bool            # LLM 后处理是否成功（失败则降级原文）
    aborted: bool = False   # 是否因被打断而放弃重写


class Pipeline:
    """编排器。

    transcribe_fn(audio) -> str：ASR 回调。
    injector：实现 type_text 的注入器。
    on_state(name)：状态回调（驱动菜单栏图标），可选。
    postprocess_fn：可注入的 LLM 后处理（默认用 llm.postprocess），便于测试。
    """

    def __init__(
        self,
        cfg: Config,
        injector,
        transcribe_fn: Callable[[object], str],
        on_state: Optional[Callable[[str], None]] = None,
        postprocess_fn: Optional[Callable[[Config, str], llm_mod.LlmResult]] = None,
    ) -> None:
        self.cfg = cfg
        self.injector = injector
        self.transcribe_fn = transcribe_fn
        self.on_state = on_state or (lambda _name: None)
        self.postprocess_fn = postprocess_fn or llm_mod.postprocess
        self._t_start: float = 0.0  # 端到端计时起点（run() 入口设定）
        self._cancelled = False     # 外部取消标志（双击停止时丢弃本段，不再注入）

    def cancel(self) -> None:
        """协作式取消：丢弃本段处理结果、不再向输入框注入。

        由外部线程（如双击停止听写）调用。已在跑的 ASR/LLM 会在后台跑完，
        但其结果不会被注入；注入前的取消闸会跳过注入。
        """
        self._cancelled = True

    def _state(self, name: str) -> None:
        try:
            self.on_state(name)
        except Exception:
            pass

    def _done(self, result: PipelineResult) -> PipelineResult:
        """统一记录端到端耗时（从接收到语音段 → 文字输出完成）并返回结果。

        覆盖全部返回路径（含纯转写、整理后注入、空结果与降级），
        使日志中始终有一条「语音→文字」总耗时，便于排查整体延迟。
        """
        _log.info("⏱ 端到端耗时(语音→文字): %.2fs", time.monotonic() - self._t_start)
        return result

    def run(self, audio) -> PipelineResult:
        """处理一段音频，返回结果。异常被吸收为降级结果（NFR-04）。"""
        # 接收到语音段的时刻：作为端到端耗时(语音→文字)的计时起点
        self._t_start = time.monotonic()
        c = self.cfg
        use_llm = llm_mod.needs_llm(c)
        n_samples = len(audio) if hasattr(audio, "__len__") else "?"
        # 只打印本次实际用到的组件，避免把无关配置也列出来造成误导
        asr_model = {
            "whisper_local": c.asr.whisper_model,
            "mlx_whisper": c.asr.mlx_model,
            "sensevoice": c.asr.sensevoice_model,
            "dashscope": c.asr.dashscope_model,
            "online": c.asr.online_model,
        }.get(c.asr.engine, "")
        _log.info("▶ 处理语音段: 样本=%s | ASR=%s(%s) 语言=%s | 后处理=%s",
                  n_samples, c.asr.engine, asr_model, c.general.language,
                  c.postprocess.mode)
        if use_llm:
            llm_model = (c.llm.ollama.model if c.llm.mode == "ollama"
                         else c.llm.online.model)
            _log.info("  实际启用 LLM: %s(%s)", c.llm.mode, llm_model)
        else:
            _log.info("  纯转写直出（本次不调用 LLM）")

        # 1) ASR
        self._state("TRANSCRIBING")
        t0 = time.monotonic()
        raw = (self.transcribe_fn(audio) or "").strip()
        t_asr = time.monotonic() - t0
        _log.info("① ASR 原始结果(%.2fs): %r", t_asr, _clip(raw))
        if not raw:
            _log.info("  (识别为空，跳过)")
            self._state("IDLE")
            return self._done(PipelineResult("", "", False, True))

        # 取消闸：识别完成后若已被取消（双击停止），丢弃本段不注入
        if self._cancelled:
            _log.info("  (已取消：丢弃本段，不注入)")
            self._state("IDLE")
            return self._done(PipelineResult(raw, "", False, True, aborted=True))

        # 整理（可选）后一次性注入：不做实时回删重写，跨 App 最稳、无残留
        final = raw
        llm_ok = True
        if use_llm:
            self._state("REFINING")
            t1 = time.monotonic()
            result = self.postprocess_fn(c, raw)
            final = result.text.strip() or raw
            llm_ok = result.ok
            _log.info("② LLM 整理(%.2fs, ok=%s): %r → %r",
                      time.monotonic() - t1, llm_ok, _clip(raw, 120), _clip(final))
            if result.error:
                _log.warning("  LLM 错误(降级): %s", result.error)
            # 防内容丢失护栏：整理结果异常偏短(疑似 LLM 截断)→ 用原文，不注入残缺结果
            if c.postprocess.mode != "translate" and _drastic_shrink(raw, final):
                _log.warning("  整理结果异常偏短(%d→%d 字)，疑似LLM异常，改用原文",
                             len(raw), len(final))
                final = raw
        # 取消闸：注入前若已被取消（双击停止），丢弃本段不注入
        if self._cancelled:
            _log.info("  (已取消：丢弃本段，不注入)")
            self._state("IDLE")
            return self._done(PipelineResult(raw, "", False, llm_ok, aborted=True))
        self._state("INJECTING")
        self.injector.type_text(final)
        _log.info("✓ 注入完成 %d 字", len(final))
        self._state("IDLE")
        return self._done(PipelineResult(raw, final, False, llm_ok))
