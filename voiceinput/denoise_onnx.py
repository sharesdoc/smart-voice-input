"""DeepFilterNet3 ONNX Runtime 降噪后端。

使用 onnxruntime 加载 DeepFilterNet3 ONNX 模型进行实时降噪。
- 支持 CoreML (Apple Silicon) 和 CPU 后端
- 自动处理 48kHz 重采样（DeepFilterNet3 要求 48kHz 输入）
- 模型加载失败时优雅降级
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .denoise import DenoiseEngine, _resolve_model_path

_log = logging.getLogger(__name__)

# DeepFilterNet3 要求的输入规格
_DF_SAMPLE_RATE = 48000
_DF_CHANNELS = 1
# 推荐帧大小：10ms @ 48kHz = 480 samples
_FRAME_SIZE = 480


class OnnxDenoiseEngine(DenoiseEngine):
    """基于 ONNX Runtime 的 DeepFilterNet3 降噪引擎。

    线程安全：process() 调用串行化（在音频回调的同一线程中）。
    """

    def __init__(
        self,
        model_path: str = "deepfilternet3.onnx",
        attenuation: float = 0.8,
        dry_wet_mix: float = 0.9,
        resample_quality: str = "fast",
    ) -> None:
        super().__init__()
        self._model_path_str = model_path
        self._attenuation = float(np.clip(attenuation, 0.0, 1.0))
        self._dry_wet_mix = float(np.clip(dry_wet_mix, 0.0, 1.0))
        self._resample_quality = resample_quality
        self._session = None
        self._available = False
        self._input_ndim = 2     # 模型输入维度（ONNX 探测前默认 2D）
        # 尝试加载模型（首次构造即加载，避免首次 process 阻塞音频线程）
        self._load_model()

    # ---- 公开属性 ----

    @property
    def available(self) -> bool:
        return self._available

    @property
    def attenuation(self) -> float:
        return self._attenuation

    @property
    def dry_wet_mix(self) -> float:
        return self._dry_wet_mix

    # ---- 内部 ----

    def _load_model(self) -> None:
        """加载 ONNX 模型。失败不抛异常，设置 available=False。"""
        model_path = _resolve_model_path(self._model_path_str)
        if model_path is None:
            _log.info("降噪模型未找到(路径: %s)，引擎不可用", self._model_path_str)
            self._available = False
            return
        try:
            import onnxruntime as ort
        except ImportError:
            _log.info("onnxruntime 未安装，降噪引擎不可用")
            self._available = False
            return
        try:
            providers = ['CPUExecutionProvider']
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL)
            self._session = ort.InferenceSession(
                str(model_path),
                sess_options=sess_options,
                providers=providers,
            )
            # 验证模型输入规格并记录维度信息
            inputs = self._session.get_inputs()
            if not inputs:
                raise ValueError("ONNX 模型没有输入节点")
            # 探测输入维度：2D (batch, samples) 或 3D (batch, channels, samples)
            inp_shape = inputs[0].shape
            self._input_ndim = len(inp_shape) if inp_shape else 2
            _log.info(
                "降噪引擎已加载: %s (providers=%s, input_shape=%s)",
                model_path.name, providers, inp_shape,
            )
            self._available = True
        except Exception as e:
            _log.warning("降噪模型加载失败(降级直通): %s: %s", type(e).__name__, e)
            self._session = None
            self._available = False

    def _resample(self, audio: np.ndarray,
                  src_rate: int, dst_rate: int) -> np.ndarray:
        """重采样音频：src_rate → dst_rate。"""
        if src_rate == dst_rate:
            return audio
        if audio.size == 0:
            return np.array([], dtype=np.float32)

        # 确保是 1D
        if audio.ndim > 1:
            audio = audio.flatten()

        ratio = dst_rate / src_rate
        if self._resample_quality == "high":
            # 高质量：FFT 重采样（需要 samplerate 包）
            try:
                import samplerate
                return samplerate.resample(
                    audio.astype(np.float32), ratio,
                    converter_type='sinc_best',
                ).astype(np.float32)
            except ImportError:
                _log.debug("samplerate 不可用，回退线性插值")
            except Exception as e:
                _log.debug("samplerate 重采样失败: %s，回退线性插值", e)

        # 快速：线性插值（CPU 友好，实时性优先）
        out_len = int(len(audio) * ratio)
        if out_len < 2:
            return np.array([], dtype=np.float32)
        src_idx = np.linspace(0, len(audio) - 1, out_len)
        idx_lo = np.floor(src_idx).astype(np.int64)
        idx_hi = np.minimum(idx_lo + 1, len(audio) - 1)
        frac = (src_idx - idx_lo).astype(np.float32)
        return (audio[idx_lo] * (1.0 - frac)
                + audio[idx_hi] * frac).astype(np.float32)

    def _process_impl(self, audio: np.ndarray,
                      sample_rate: int) -> np.ndarray:
        """ONNX 降噪处理流程。

        步骤：
        1. 展平为 mono（多声道取平均）
        2. 重采样到 48kHz
        3. 分帧送入 ONNX 推理
        4. 重采样回原始采样率
        5. dry/wet mix 混合
        """
        if self._session is None or not self._available:
            return audio

        # 1) 展平为 mono
        if audio.ndim > 1:
            audio_mono = audio.mean(axis=1).astype(np.float32)
        else:
            audio_mono = audio.astype(np.float32)
        original_shape = audio.shape

        # 2) 重采样到 48kHz
        audio_48k = self._resample(audio_mono, sample_rate, _DF_SAMPLE_RATE)
        if audio_48k.size == 0:
            return audio

        # 3) ONNX 推理：逐帧处理
        # DeepFilterNet3 ONNX 模型输入: (batch, channels, samples) 或 (batch, samples)
        # 尝试获取模型输入名和形状
        try:
            input_name = self._session.get_inputs()[0].name
            output_name = self._session.get_outputs()[0].name
        except Exception:
            return audio

        # 对整个音频块做单次推理（如果音频太长则分段）
        MAX_CHUNK = _DF_SAMPLE_RATE * 10  # 最多 10 秒一块
        processed_parts = []

        for start in range(0, len(audio_48k), MAX_CHUNK):
            chunk = audio_48k[start:start + MAX_CHUNK]
            # 确保 float32
            chunk = chunk.astype(np.float32)
            # 添加 batch 维度，适配模型输入
            if self._input_ndim <= 2:
                # 2D 输入: (batch, samples)
                chunk_batch = np.expand_dims(chunk, axis=0)
            else:
                # 3D 输入: (batch, channels, samples)
                chunk_batch = np.expand_dims(
                    np.expand_dims(chunk, axis=0), axis=0)

            try:
                ort_inputs = {input_name: chunk_batch}
                ort_outputs = self._session.run([output_name], ort_inputs)
                out_chunk = ort_outputs[0]
            except Exception as e:
                _log.warning("ONNX 推理失败(直通): %s", e)
                processed_parts.append(chunk)
                continue

            # 处理输出：可能为 (1, samples) 或 (1, 1, samples)
            if out_chunk.ndim == 3:
                out_chunk = out_chunk[0, 0, :]
            elif out_chunk.ndim == 2:
                out_chunk = out_chunk[0, :]
            out_chunk = out_chunk.flatten().astype(np.float32)

            # 6) 应用降噪强度 (attenuation) 作为输出增益衰减
            #    attenuation=1.0 → 全降噪输出; attenuation=0.0 → 直通
            if self._attenuation < 1.0:
                mix_chunk = (self._attenuation * out_chunk
                             + (1.0 - self._attenuation) * chunk)
            else:
                mix_chunk = out_chunk

            # 7) dry/wet mix：控制降噪输出与原始信号的混合比例
            if self._dry_wet_mix < 1.0:
                out_chunk = (self._dry_wet_mix * mix_chunk
                             + (1.0 - self._dry_wet_mix) * chunk)
            else:
                out_chunk = mix_chunk

            processed_parts.append(out_chunk)

        denoised_48k = np.concatenate(processed_parts).astype(np.float32)

        # 4) 重采样回原始采样率
        denoised = self._resample(denoised_48k, _DF_SAMPLE_RATE, sample_rate)

        # 5) 恢复原始 shape
        if denoised.size == 0:
            return audio
        if len(original_shape) > 1 and original_shape[1] > 1:
            # 多声道：复制到所有声道
            denoised = np.tile(denoised.reshape(-1, 1), (1, original_shape[1]))

        # 长度对齐：截断到原始长度（16k↔48k 整数比，降采样后最多差 1 样本）
        orig_len = original_shape[0]
        if len(denoised) > orig_len:
            denoised = denoised[:orig_len]

        if len(original_shape) > 1:
            denoised = denoised.reshape(original_shape)

        return denoised.astype(np.float32)
