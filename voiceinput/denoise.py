"""DeepFilterNet3 降噪引擎封装。

设计原则：
  - 默认不加载模型（节省内存），首次使用时懒加载
  - 加载失败时自动降级为直通（dry signal），不阻断录音链路
  - 处理异常时返回原始音频 + 记录日志，绝不抛异常到调用方
  - 所有耗时操作在独立线程中完成，保持音频回调轻量
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import DenoiseConfig

_log = logging.getLogger(__name__)


@dataclass
class DenoiseStats:
    """一次降噪处理的统计信息（用于日志和调试）。"""
    input_rms: float = 0.0
    output_rms: float = 0.0
    reduction_db: float = 0.0      # 负值 = 噪声被抑制
    processing_ms: float = 0.0


def _resolve_model_path(raw: str) -> Optional[Path]:
    """解析模型路径：绝对路径直接返回；相对路径在搜索目录中查找。

    Args:
        raw: 用户配置的原始路径字符串

    Returns:
        找到的模型文件路径；找不到返回 None。
    """
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p if p.exists() else None
    # 相对路径：在 config_dir/models 下查找
    from .config import config_dir
    base = config_dir()
    candidates = [
        base / raw,
        base / "models" / raw,
        Path(raw),                             # 当前工作目录
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def make_denoise_engine(cfg: DenoiseConfig):
    """根据配置创建降噪引擎实例。

    Args:
        cfg: 降噪配置

    Returns:
        DenoiseEngine 实例，或 None（引擎不可用/未启用）。
    """
    if not cfg.enabled:
        return None
    if cfg.engine == "onnx":
        from .denoise_onnx import OnnxDenoiseEngine
        engine = OnnxDenoiseEngine(
            model_path=cfg.onnx_model_path,
            attenuation=cfg.attenuation,
            dry_wet_mix=cfg.dry_wet_mix,
            resample_quality=cfg.resample_quality,
        )
        return engine if engine.available else None
    elif cfg.engine == "subprocess":
        _log.warning("subprocess 降噪引擎尚未实现，降级为直通")
        return None
    else:
        _log.warning("未知降噪引擎: %s", cfg.engine)
        return None


def _rms(audio: np.ndarray) -> float:
    """计算音频 RMS（与 audio.rms 一致）。"""
    if audio.size == 0:
        return 0.0
    sq = np.mean(audio.astype(np.float64) ** 2)
    return float(np.sqrt(sq))


class DenoiseEngine:
    """降噪引擎基类。

    子类只需实现 _process_impl()；基类负责统计信息和异常保护。
    """

    def __init__(self) -> None:
        self._stats = DenoiseStats()

    @property
    def available(self) -> bool:
        """引擎模型是否已成功加载。子类必须覆盖。"""
        raise NotImplementedError

    @property
    def stats(self) -> DenoiseStats:
        """最近一次处理的统计信息。"""
        return self._stats

    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """处理一段音频，返回降噪后的音频（同采样率、同 shape）。

        异常安全：任何异常都返回原始音频（直通），不阻断链路。

        Args:
            audio: float32 numpy array, shape (samples, channels) 或 (samples,)
            sample_rate: 当前采样率

        Returns:
            降噪后音频（与原输入同采样率、同 shape）。
        """
        if not self.available:
            return audio
        try:
            rms_in = _rms(audio) if audio.size > 0 else 0.0
            t0 = time.monotonic()
            out = self._process_impl(audio, sample_rate)
            elapsed = (time.monotonic() - t0) * 1000
            rms_out = _rms(out) if out.size > 0 else 0.0
            reduction = (20.0 * np.log10(max(rms_out, 1e-10)
                         / max(rms_in, 1e-10))) if rms_in > 1e-10 else 0.0
            self._stats = DenoiseStats(
                input_rms=round(rms_in, 6),
                output_rms=round(rms_out, 6),
                reduction_db=round(reduction, 2),
                processing_ms=round(elapsed, 2),
            )
            return out
        except Exception:
            _log.exception("降噪处理异常，直通原始音频")
            return audio

    def _process_impl(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """子类实现：实际的降噪处理逻辑。"""
        raise NotImplementedError
