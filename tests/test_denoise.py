"""神经网络降噪模块测试。

覆盖：
  - DenoiseConfig 默认值与序列化
  - make_denoise_engine 工厂行为
  - DenoiseEngine 基类（降级直通、异常保护、统计信息）
  - OnnxDenoiseEngine（重采样、dry/wet mix）
  - Recorder 降噪参数传递
"""

from __future__ import annotations

import numpy as np
import pytest

from voiceinput.config import Config, DenoiseConfig
from voiceinput.denoise import (
    DenoiseEngine, DenoiseStats, _rms,
    _resolve_model_path, make_denoise_engine,
)
from voiceinput.denoise_onnx import OnnxDenoiseEngine


# ── DenoiseConfig ──────────────────────────────────────────────

def test_denoise_config_defaults():
    """降噪配置默认值：关闭、ONNX 引擎、合理衰减参数。"""
    c = DenoiseConfig()
    assert c.enabled is False
    assert c.engine == "onnx"
    assert c.attenuation == 0.8
    assert c.dry_wet_mix == 0.9
    assert c.resample_quality == "fast"


def test_denoise_config_in_config():
    """Config 聚合根包含 denoise 子配置。"""
    cfg = Config()
    assert cfg.denoise.enabled is False
    d = cfg.to_dict()
    assert "denoise" in d
    assert d["denoise"]["enabled"] is False


def test_denoise_config_roundtrip():
    """序列化/反序列化后降噪配置不变。"""
    cfg = Config()
    cfg.denoise.enabled = True
    cfg.denoise.attenuation = 0.5
    cfg2 = Config.from_dict(cfg.to_dict())
    assert cfg2.denoise.enabled is True
    assert cfg2.denoise.attenuation == 0.5


def test_denoise_config_partial_load():
    """配置文件缺少 denoise 段时自动填充默认值。"""
    cfg = Config.from_dict({"general": {"language": "en"}})
    assert cfg.denoise.enabled is False
    assert cfg.denoise.attenuation == 0.8


# ── make_denoise_engine ────────────────────────────────────────

def test_make_denoise_engine_disabled():
    """降噪关闭时工厂返回 None。"""
    cfg = DenoiseConfig(enabled=False)
    assert make_denoise_engine(cfg) is None


def test_make_denoise_engine_onnx_no_model():
    """ONNX 引擎启用但模型不存在 → 返回 None（静默降级）。"""
    cfg = DenoiseConfig(
        enabled=True, engine="onnx",
        onnx_model_path="/nonexistent/path/model.onnx",
    )
    engine = make_denoise_engine(cfg)
    # 模型不存在时返回 None（无 onnxruntime 或文件找不到）
    assert engine is None


def test_make_denoise_engine_unknown_engine():
    """未知引擎类型返回 None。"""
    cfg = DenoiseConfig(enabled=True, engine="unknown_xyz")
    engine = make_denoise_engine(cfg)
    assert engine is None


# ── _rms ───────────────────────────────────────────────────────

def test_rms_zero_for_silence():
    assert _rms(np.zeros(100, dtype=np.float32)) == 0.0


def test_rms_positive_for_signal():
    audio = np.full(100, 0.2, dtype=np.float32)
    assert _rms(audio) == pytest.approx(0.2, abs=0.001)


# ── DenoiseStats ───────────────────────────────────────────────

def test_denoise_stats_fields():
    s = DenoiseStats(input_rms=0.1, output_rms=0.05,
                     reduction_db=-6.0, processing_ms=15.2)
    assert s.reduction_db == -6.0
    assert s.processing_ms == 15.2


# ── DenoiseEngine base ─────────────────────────────────────────

class _MockEngine(DenoiseEngine):
    """最小实现：恒通引擎（无降噪，只验证框架）。"""

    def __init__(self, available: bool = True,
                 processed_flag: bool = False):
        super().__init__()
        self._available = available
        self.processed_flag = processed_flag

    @property
    def available(self) -> bool:
        return self._available

    def _process_impl(self, audio, sample_rate):
        self.processed_flag = True
        return audio * 0.5  # 人为衰减一半


def test_engine_process_available():
    """可用引擎正常处理音频。"""
    engine = _MockEngine(available=True)
    audio = np.full(100, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert engine.processed_flag is True
    assert out.shape == audio.shape
    assert np.allclose(out, audio * 0.5)
    # 验证统计信息
    assert engine.stats.input_rms > 0
    assert engine.stats.output_rms > 0
    assert engine.stats.reduction_db < 0  # 衰减 = 负 dB
    assert engine.stats.processing_ms >= 0


def test_engine_process_unavailable_returns_original():
    """引擎不可用时返回原始音频（直通）。"""
    engine = _MockEngine(available=False)
    audio = np.full(100, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert engine.processed_flag is False
    assert out is audio


def test_engine_process_exception_returns_original():
    """处理异常时返回原始音频，不抛异常。"""

    class _CrashingEngine(_MockEngine):
        def _process_impl(self, audio, sample_rate):
            raise RuntimeError("模拟降噪崩溃")

    engine = _CrashingEngine(available=True)
    audio = np.full(100, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio  # 异常后直通


def test_engine_process_multichannel():
    """多声道输入也能正常处理。"""
    engine = _MockEngine(available=True)
    audio = np.full((100, 2), 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape


# ── OnnxDenoiseEngine ──────────────────────────────────────────

def test_onnx_engine_unavailable_without_model():
    """模型不存在时 OnnxDenoiseEngine.available = False。"""
    engine = OnnxDenoiseEngine(
        model_path="/nonexistent/model.onnx",
        attenuation=0.8, dry_wet_mix=0.9,
    )
    assert engine.available is False
    # process 应返回原始音频
    audio = np.full(200, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_engine_attenuation_clamped():
    """attenuation/dry_wet_mix 超出 [0,1] 时自动夹紧。"""
    e1 = OnnxDenoiseEngine(attenuation=3.0, dry_wet_mix=-0.5)
    assert e1.attenuation == 1.0
    assert e1.dry_wet_mix == 0.0


def test_onnx_resample_identity():
    """同采样率重采样 = 恒等（允许微小浮点差异）。"""
    engine = OnnxDenoiseEngine()
    audio = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
    out = engine._resample(audio, 48000, 48000)
    assert out.shape == audio.shape
    assert np.allclose(out, audio, atol=1e-6)


def test_onnx_resample_upsample():
    """16k → 48k 升采样后长度比例正确。"""
    engine = OnnxDenoiseEngine()
    audio = np.linspace(-0.5, 0.5, 160, dtype=np.float32)  # 10ms
    out = engine._resample(audio, 16000, 48000)
    expected_len = len(audio) * 3  # 48000/16000 = 3
    assert abs(len(out) - expected_len) <= 1


def test_onnx_resample_downsample():
    """48k → 16k 降采样后长度比例正确。"""
    engine = OnnxDenoiseEngine()
    audio = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
    out = engine._resample(audio, 48000, 16000)
    expected_len = len(audio) // 3
    assert abs(len(out) - expected_len) <= 1


def test_onnx_resample_empty():
    """空输入返回空数组。"""
    engine = OnnxDenoiseEngine()
    out = engine._resample(np.array([], dtype=np.float32), 16000, 48000)
    assert out.size == 0


# ── Recorder 集成 ──────────────────────────────────────────────

def test_recorder_stores_denoise_engine():
    """Recorder 接受并存储降噪引擎参数。"""
    from voiceinput.audio import Recorder, SilenceDetector

    vad = SilenceDetector(silence_threshold=0.036, silence_sec=1.0,
                          min_speech_sec=0.3)
    engine = _MockEngine(available=True)
    rec = Recorder(vad=vad, denoise=engine)
    assert rec._denoise is engine


def test_recorder_denoise_none_by_default():
    """不传降噪时 Recorder._denoise 为 None。"""
    from voiceinput.audio import Recorder
    rec = Recorder()
    assert rec._denoise is None


# ── _resolve_model_path ────────────────────────────────────────

def test_resolve_model_path_empty():
    """空路径返回 None。"""
    assert _resolve_model_path("") is None


def test_resolve_model_path_nonexistent():
    """不存在的路径返回 None。"""
    assert _resolve_model_path("/nonexistent/deepfilter.ONNX") is None


# ── OnnxDenoiseEngine with mocked ONNX session ──────────────────

class _FakeSession:
    """模拟 ONNX InferenceSession，接受任意输入并做轻度衰减。"""

    def __init__(self, input_name="input", output_name="output",
                 inp_shape=(1, 480), ndim=2):
        self._input_name = input_name
        self._output_name = output_name
        self._inp_shape = inp_shape
        self._ndim = ndim

    def get_inputs(self):
        class _Inp:
            def __init__(self, name, shape):
                self.name = name
                self.shape = shape
        return [_Inp(self._input_name, self._inp_shape)]

    def get_outputs(self):
        class _Out:
            def __init__(self, name):
                self.name = name
        return [_Out(self._output_name)]

    def run(self, outputs, inputs):
        key = list(inputs.keys())[0]
        val = inputs[key]
        # 模拟降噪：衰减 30%（模拟噪声抑制）
        attenuated = val * 0.7
        return [attenuated.astype(np.float32)]


def _make_fake_engine(attenuation=1.0, dry_wet_mix=1.0,
                      resample_quality="fast",
                      inp_shape=(1, 480), ndim=2):
    """创建带 mock session 的 OnnxDenoiseEngine。"""
    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._model_path_str = "fake.onnx"
    engine._attenuation = float(np.clip(attenuation, 0.0, 1.0))
    engine._dry_wet_mix = float(np.clip(dry_wet_mix, 0.0, 1.0))
    engine._resample_quality = resample_quality
    engine._input_ndim = ndim
    engine._session = _FakeSession(inp_shape=inp_shape, ndim=ndim)
    engine._available = True
    return engine


def test_onnx_process_basic():
    """mock session：16kHz mono → 降噪 → 同 shape 输出。"""
    engine = _make_fake_engine()
    audio = np.full(1600, 0.2, dtype=np.float32)  # 100ms @ 16kHz
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape
    assert out.dtype == np.float32
    # 应有统计信息
    assert engine.stats.input_rms > 0
    assert engine.stats.processing_ms >= 0


def test_onnx_process_with_attenuation():
    """attenuation=0.5 时输出介于直通和全降噪之间。"""
    # 全降噪引擎
    eng_full = _make_fake_engine(attenuation=1.0, dry_wet_mix=1.0)
    audio = np.full(800, 0.3, dtype=np.float32)
    out_full = eng_full.process(audio, 16000)

    # attenuation=0 引擎（完全直通）
    eng_none = _make_fake_engine(attenuation=0.0, dry_wet_mix=1.0)
    out_none = eng_none.process(audio, 16000)

    # out_none 应接近原始（模拟 session 衰减的再通过 atten=0 混合 = 原始）
    assert np.allclose(out_none, audio, atol=0.05)
    # out_full 应不同于原始（经过 session 衰减）
    assert not np.allclose(out_full, audio, atol=0.05)


def test_onnx_process_dry_wet_mix():
    """dry_wet_mix=0 应直通原始音频。"""
    engine = _make_fake_engine(attenuation=1.0, dry_wet_mix=0.0)
    audio = np.full(800, 0.3, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert np.allclose(out, audio, atol=0.05)


def test_onnx_process_multichannel():
    """多声道输入 → 降噪 → 多声道输出。"""
    engine = _make_fake_engine()
    audio = np.full((1600, 2), 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape
    assert out.dtype == np.float32


def test_onnx_process_large_chunk():
    """长音频（>10s @ 48kHz）会分块处理。"""
    engine = _make_fake_engine()
    # 约 12 秒 @ 16kHz → 约 36 秒等量 @ 48kHz，触发分块
    audio = np.full(12 * 16000, 0.15, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape
    assert out.dtype == np.float32


def test_onnx_process_session_none():
    """session 为 None 时直通。"""
    engine = _make_fake_engine()
    engine._session = None
    engine._available = False
    audio = np.full(400, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_process_3d_input():
    """3D 输入模型 (batch, channels, samples) 也正常工作。"""
    engine = _make_fake_engine(inp_shape=(1, 1, 480), ndim=3)
    audio = np.full(1600, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape


def test_onnx_process_resample_quality_high():
    """resample_quality=high 路径。若无 samplerate 则自动回退。"""
    engine = _make_fake_engine(resample_quality="high")
    audio = np.full(1600, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape


def test_onnx_resample_2d_input():
    """2D 音频在重采样前被展平。"""
    engine = OnnxDenoiseEngine()
    audio = np.full((400, 1), 0.2, dtype=np.float32)
    out = engine._resample(audio, 16000, 48000)
    assert out.ndim == 1
    assert len(out) > len(audio)


def test_onnx_resample_very_short():
    """极短音频升采样后长度不足 2 → 返回空数组。"""
    engine = OnnxDenoiseEngine()
    # 1 sample @ 16k → 3 samples @ 48k（线性插值只在两端）
    audio = np.array([0.5], dtype=np.float32)
    out = engine._resample(audio, 16000, 48000)
    # 长度至少为 2（out_len = int(1 * 3) = 3）
    assert len(out) >= 2


def test_onnx_resample_very_short_downsample():
    """极短音频降采样后可能为空。"""
    engine = OnnxDenoiseEngine()
    audio = np.array([0.5, 0.6], dtype=np.float32)  # 2 samples
    out = engine._resample(audio, 48000, 16000)
    # 向下取整 int(2 * 1/3) = 0，为空
    assert out.size == 0


def test_denoise_config_roundtrip_full():
    """完整 DenoiseConfig 序列化/反序列化。"""
    cfg = Config()
    cfg.denoise.enabled = True
    cfg.denoise.attenuation = 0.6
    cfg.denoise.dry_wet_mix = 0.7
    cfg.denoise.resample_quality = "high"
    cfg.denoise.engine = "onnx"
    cfg.denoise.onnx_model_path = "/test/model.onnx"
    cfg2 = Config.from_dict(cfg.to_dict())
    dc = cfg2.denoise
    assert dc.enabled is True
    assert dc.attenuation == 0.6
    assert dc.dry_wet_mix == 0.7
    assert dc.resample_quality == "high"


def test_make_denoise_engine_subprocess_unsupported():
    """subprocess 引擎返回 None。"""
    cfg = DenoiseConfig(enabled=True, engine="subprocess")
    assert make_denoise_engine(cfg) is None


# ── _resolve_model_path 相对路径解析 ────────────────────────────

def test_resolve_model_path_relative_found(tmp_path, monkeypatch):
    """相对路径在 config_dir/models 下找到时返回正确路径。"""
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "test.onnx"
    model_file.write_text("fake")
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    result = _resolve_model_path("test.onnx")
    assert result is not None
    assert result.name == "test.onnx"


def test_resolve_model_path_absolute_found(tmp_path):
    """绝对路径存在时直接返回。"""
    model_file = tmp_path / "abs_model.onnx"
    model_file.write_text("fake")
    result = _resolve_model_path(str(model_file))
    assert result == model_file


# ── _load_model 完整路径（mock onnxruntime）─────────────────────

def test_onnx_load_model_success(tmp_path, monkeypatch):
    """mock onnxruntime → _load_model 成功设置 available=True。"""
    model_file = tmp_path / "fake.onnx"
    model_file.write_text("dummy")

    class _FakeORT:
        @staticmethod
        def get_available_providers():
            return ['CPUExecutionProvider']

        class GraphOptimizationLevel:
            ORT_ENABLE_ALL = 1

        @staticmethod
        def SessionOptions():
            from unittest.mock import MagicMock
            return MagicMock()

        @staticmethod
        def InferenceSession(path, sess_options=None, providers=None):
            return _FakeSession()

    monkeypatch.setattr(
        "voiceinput.denoise_onnx._resolve_model_path",
        lambda raw: model_file,
    )
    monkeypatch.setitem(
        __import__('sys').modules, "onnxruntime", _FakeORT,
    )

    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._model_path_str = "fake.onnx"
    engine._attenuation = 1.0
    engine._dry_wet_mix = 1.0
    engine._resample_quality = "fast"
    engine._available = False
    engine._input_ndim = 2
    engine._load_model()
    assert engine.available is True
    assert engine._session is not None
    assert engine._input_ndim == 2


def test_onnx_load_model_import_error(monkeypatch):
    """onnxruntime 未安装 → available=False。"""
    monkeypatch.setattr(
        "voiceinput.denoise_onnx._resolve_model_path",
        lambda raw: __import__('pathlib').Path("/fake/model.onnx"),
    )
    # 模拟 onnxruntime 导入失败
    import builtins
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "onnxruntime":
            raise ImportError("No module named 'onnxruntime'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._model_path_str = "fake.onnx"
    engine._available = True
    engine._load_model()
    assert engine.available is False


# ── _process_impl 边界与异常路径 ─────────────────────────────────

def test_onnx_process_session_none_available_true():
    """session=None 但 available=True → 直通（边界防御）。"""
    engine = _make_fake_engine()
    engine._session = None
    engine._available = True
    audio = np.full(400, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_process_get_inputs_exception():
    """session.get_inputs() 抛异常 → 直通。"""
    engine = _make_fake_engine()

    class _BadSession:
        def get_inputs(self):
            raise RuntimeError("模型损坏")

    engine._session = _BadSession()
    audio = np.full(400, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_process_inference_exception():
    """session.run() 抛异常 → 该 chunk 直通，继续处理。"""
    engine = _make_fake_engine()

    class _BadRunSession:
        def get_inputs(self):
            class _Inp:
                name = "x"
                shape = (1, 480)
            return [_Inp()]

        def get_outputs(self):
            class _Out:
                name = "y"
            return [_Out()]

        def run(self, outputs, inputs):
            raise RuntimeError("推理崩溃")

    engine._session = _BadRunSession()
    audio = np.full(1600, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape  # 直通但不丢数据


def test_onnx_process_empty_after_resample():
    """48k 重采样后为空 → 直通。"""
    engine = _make_fake_engine()
    # 极短音频升采样后长度可能为 0
    audio = np.array([0.5], dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_process_3d_output():
    """ONNX 输出 3D (1,1,samples) → 正确展平。"""

    class _3DSession:
        def get_inputs(self):
            class _Inp:
                name = "x"
                shape = (1, 480)
            return [_Inp()]

        def get_outputs(self):
            class _Out:
                name = "y"
            return [_Out()]

        def run(self, outputs, inputs):
            val = list(inputs.values())[0]
            # 返回 3D 输出: (1, 1, samples)
            return [np.expand_dims(val, axis=1).astype(np.float32)]

    engine = _make_fake_engine()
    engine._session = _3DSession()
    audio = np.full(1600, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape


def test_onnx_process_truncation():
    """降采样后长度超原始 → 截断对齐。"""
    engine = _make_fake_engine()

    # 使 _resample 返回比原音频长的结果：mock _resample
    orig_resample = engine._resample

    def _longer_resample(audio, src, dst):
        out = orig_resample(audio, src, dst)
        if dst < src and out.size > 0:
            # 人为拉长使降采样结果 > 原始长度
            return np.pad(out, (0, 10), mode='constant')
        return out

    engine._resample = _longer_resample
    audio = np.full(960, 0.2, dtype=np.float32)  # 足够长避免空数组
    out = engine.process(audio, 16000)
    assert len(out) == len(audio)


# ── 高质量重采样路径 ─────────────────────────────────────────────

def test_onnx_resample_high_quality_samplerate_available(monkeypatch):
    """mock samplerate 可用 → 走 FFT 重采样路径。"""
    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._resample_quality = "high"

    class _FakeSamplerate:
        @staticmethod
        def resample(audio, ratio, converter_type=None):
            # 模拟高质量重采样：执行简单线性插值
            out_len = int(len(audio) * ratio)
            src_idx = np.linspace(0, len(audio) - 1, max(out_len, 1))
            idx_lo = np.floor(src_idx).astype(np.int64)
            idx_hi = np.minimum(idx_lo + 1, len(audio) - 1)
            frac = (src_idx - idx_lo).astype(np.float32)
            return (audio[idx_lo] * (1.0 - frac)
                    + audio[idx_hi] * frac).astype(np.float32)

    monkeypatch.setitem(
        __import__('sys').modules, "samplerate", _FakeSamplerate,
    )

    audio = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
    out = engine._resample(audio, 16000, 48000)
    assert len(out) == int(len(audio) * 3)


def test_onnx_resample_high_quality_samplerate_error(monkeypatch):
    """samplerate.resample 抛异常 → 回退线性插值。"""
    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._resample_quality = "high"

    class _BadSamplerate:
        @staticmethod
        def resample(audio, ratio, converter_type=None):
            raise RuntimeError("重采样引擎崩溃")

    monkeypatch.setitem(
        __import__('sys').modules, "samplerate", _BadSamplerate,
    )

    audio = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
    out = engine._resample(audio, 16000, 48000)
    assert len(out) == int(len(audio) * 3)  # 回退成功


# ── denoise.py 边界覆盖 ─────────────────────────────────────────

def test_denoise_engine_available_not_implemented():
    """基类 available 属性抛 NotImplementedError。"""
    engine = DenoiseEngine.__new__(DenoiseEngine)
    DenoiseEngine.__init__(engine)
    with pytest.raises(NotImplementedError):
        _ = engine.available


def test_denoise_engine_process_impl_not_implemented():
    """基类 _process_impl 抛 NotImplementedError。"""
    engine = DenoiseEngine.__new__(DenoiseEngine)
    DenoiseEngine.__init__(engine)
    with pytest.raises(NotImplementedError):
        engine._process_impl(np.zeros(10, dtype=np.float32), 16000)


# ── 覆盖剩余未命中行：denoise.py L93, denoise_onnx L96/105-108/171/233/250 ──

def test_rms_empty_audio():
    """_rms 空输入 → return 0.0 (覆盖 L93)。"""
    assert _rms(np.array([], dtype=np.float32)) == 0.0


def test_onnx_load_model_no_inputs(monkeypatch, tmp_path):
    """session.get_inputs() 返回空列表 → ValueError 被捕获 (覆盖 L93)。"""
    model_file = tmp_path / "noinp.onnx"
    model_file.write_text("dummy")

    class _NoInputSession:
        def __init__(self, path, sess_options=None, providers=None):
            pass
        def get_inputs(self):
            return []

    class _FakeORT:
        @staticmethod
        def get_available_providers():
            return ['CPUExecutionProvider']

        class GraphOptimizationLevel:
            ORT_ENABLE_ALL = 1

        @staticmethod
        def SessionOptions():
            from unittest.mock import MagicMock
            return MagicMock()

        @staticmethod
        def InferenceSession(path, sess_options=None, providers=None):
            return _NoInputSession(path, sess_options=sess_options,
                                   providers=providers)

    monkeypatch.setattr(
        "voiceinput.denoise_onnx._resolve_model_path",
        lambda raw: model_file,
    )
    monkeypatch.setitem(
        __import__('sys').modules, "onnxruntime", _FakeORT,
    )

    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._model_path_str = "noinp.onnx"
    engine._available = True
    engine._load_model()
    assert engine.available is False


def test_onnx_load_model_session_creation_fails(monkeypatch, tmp_path):
    """InferenceSession 构造失败 → except 块捕获 (覆盖 L105-108)。"""
    model_file = tmp_path / "bad.onnx"
    model_file.write_text("dummy")

    class _FakeORT:
        @staticmethod
        def get_available_providers():
            return ['CPUExecutionProvider']

        class GraphOptimizationLevel:
            ORT_ENABLE_ALL = 1

        @staticmethod
        def SessionOptions():
            from unittest.mock import MagicMock
            return MagicMock()

        @staticmethod
        def InferenceSession(path, sess_options=None, providers=None):
            raise RuntimeError("模型文件损坏")

    monkeypatch.setattr(
        "voiceinput.denoise_onnx._resolve_model_path",
        lambda raw: model_file,
    )
    monkeypatch.setitem(
        __import__('sys').modules, "onnxruntime", _FakeORT,
    )

    engine = OnnxDenoiseEngine.__new__(OnnxDenoiseEngine)
    DenoiseEngine.__init__(engine)
    engine._model_path_str = "bad.onnx"
    engine._available = True
    engine._load_model()
    assert engine.available is False
    assert engine._session is None


def test_onnx_process_empty_after_48k_resample():
    """空音频输入 → 48k 重采样后为空 → 直通 (覆盖 L168)。"""
    engine = _make_fake_engine()
    audio = np.array([], dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out is audio


def test_onnx_process_all_chunks_fail():
    """所有 chunk 推理失败 → 逐 chunk 直通追加，最终拼接还原。"""

    class _AlwaysFailSession:
        def get_inputs(self):
            class _Inp:
                name = "x"
                shape = (1, 480)
            return [_Inp()]

        def get_outputs(self):
            class _Out:
                name = "y"
            return [_Out()]

        def run(self, outputs, inputs):
            raise RuntimeError("永远失败")

    engine = _make_fake_engine()
    engine._session = _AlwaysFailSession()
    audio = np.full(1600, 0.2, dtype=np.float32)
    out = engine.process(audio, 16000)
    assert out.shape == audio.shape
    assert out.dtype == np.float32


