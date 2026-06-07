"""麦克风录音封装 + 静音自动断句 (FR-03/FR-04)。

使用 sounddevice 采集 16kHz 单声道 PCM（Whisper 所需），懒加载依赖。
提供切换式录音：start() 开始，stop() 返回 float32 numpy 音频；
可选 VAD：检测到一段语音后持续静音超过阈值即触发自动结束回调。

SilenceDetector 为纯逻辑（喂入音频块返回是否应结束），便于单测。
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Optional

_log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1

# 软封顶放宽后的静音下限：单段过长时所需静音最多缩到这么短再去找停顿 (X-103)。
_MIN_RELAX_SILENCE = 0.15


def rms(chunk) -> float:
    """计算音频块的均方根能量。接受 numpy 数组或可迭代序列。"""
    import numpy as np

    arr = np.asarray(chunk, dtype="float32").flatten()
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))


def voiced_seconds(audio, threshold: float, sample_rate: int = 16000,
                   win_ms: int = 30) -> float:
    """音频中"有声"(RMS≥threshold)部分的累计时长（秒）。

    即去掉静音/背景噪音后真正有声的时长，与 VAD 同口径（按 win_ms 分帧逐帧判能量）。
    用于底噪幻觉拦截：识别出 N 字却没几声真语音 → 判幻觉。threshold 取 VAD 静音阈值。
    """
    import numpy as np

    arr = np.asarray(audio, dtype="float32").flatten()
    if arr.size == 0:
        return 0.0
    win = max(1, int(sample_rate * win_ms / 1000))
    total = 0.0
    for i in range(0, arr.size, win):
        frame = arr[i:i + win]
        if frame.size and float(np.sqrt(np.mean(frame * frame))) >= threshold:
            total += frame.size / sample_rate
    return total


class SilenceDetector:
    """静音自动断句判定 (FR-04)，纯逻辑。

    规则：本段一旦出现过有效语音，若连续静音时长 >= 当前所需静音阈值，feed()
    返回 True 表示应结束。所需静音阈值正常等于 silence_sec；当单段过长时由软封顶
    机制逐步放宽（见 _required_silence_sec / X-103）。

    软封顶 (soft_cap_sec / hard_cap_sec)：针对"放录音/少停顿"场景——单段时长超过
    soft_cap_sec 后，所需静音从 silence_sec 线性缩短，使长段能就近在微停顿处切开
    （尽量切在自然停顿，少伤语义）；到 hard_cap_sec 仍无任何可用停顿则硬切兜底。
    两者 <=0 表示禁用软封顶（默认），退化为纯 silence_sec 判定。
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        silence_threshold: float = 0.01,
        silence_sec: float = 1.2,
        min_speech_sec: float = 0.3,
        soft_cap_sec: float = 0.0,
        hard_cap_sec: float = 0.0,
        soft_cap_step_sec: float = 60.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.soft_cap_sec = soft_cap_sec           # 单段超此时长开始放宽所需静音（<=0 禁用）
        self.hard_cap_sec = hard_cap_sec           # 单段达此时长强制硬切兜底（<=0 禁用）
        self.soft_cap_step_sec = soft_cap_step_sec # 阶梯减半的步进间隔（秒）
        self._speech_accum = 0.0   # 已累计语音时长
        self._silence_accum = 0.0  # 当前连续静音时长
        self._segment_accum = 0.0  # 本段总时长（语音+静音），软封顶据此放宽
        self._had_speech = False
        self._soft_cap_entered = False   # 是否已进入软封顶区间
        self._last_logged_req: float | None = None  # 上次日志记录的 required_silence

    def reset(self) -> None:
        self._speech_accum = 0.0
        self._silence_accum = 0.0
        self._segment_accum = 0.0
        self._had_speech = False
        self._soft_cap_entered = False
        self._last_logged_req = None

    @property
    def _soft_cap_enabled(self) -> bool:
        """软封顶是否整体生效：需 soft_cap_sec>0 且 hard_cap_sec>soft_cap_sec。

        任一不满足（≤0 或 hard≤soft）则放宽与硬切都不生效，退化为纯 silence_sec
        判定——避免"只设 hard 不设 soft"时硬切单独触发的歧义 (X-103 审查整改)。
        """
        return (self.soft_cap_sec > 0 and self.hard_cap_sec > self.soft_cap_sec
                and self.soft_cap_step_sec > 0)

    def _required_silence_sec(self) -> float:
        """当前所需的连续静音时长：正常 = silence_sec；超 soft_cap 后阶梯减半。

        每 soft_cap_step_sec 秒步进一次，每次减半：1.0→0.5→0.25→0.15(底)。
        """
        base = self.silence_sec
        if not self._soft_cap_enabled or self._segment_accum < self.soft_cap_sec:
            return base
        steps = 1 + int((self._segment_accum - self.soft_cap_sec) / self.soft_cap_step_sec)
        req = base
        for _ in range(steps):
            req = max(req / 2.0, _MIN_RELAX_SILENCE)
        return req

    def speech_sec(self) -> float:
        """本段已累计的语音时长（秒）。即切段时"去静音后的有声秒数"，

        与切段同口径（逐块判能量累加），比 pipeline 事后用固定窗重测更准——
        避免把真语音漏算成 0。供噪音判定使用。
        """
        return self._speech_accum

    def feed(self, chunk) -> bool:
        """喂入一块音频，返回是否应结束录音。"""
        n = len(chunk)
        if n == 0:
            return False
        dur = n / self.sample_rate
        self._segment_accum += dur
        if rms(chunk) >= self.silence_threshold:
            # 语音
            self._speech_accum += dur
            self._silence_accum = 0.0
            if self._speech_accum >= self.min_speech_sec:
                self._had_speech = True
        else:
            # 静音
            self._silence_accum += dur
        # 软封顶硬上限：无论有无语音，段长超标即强制切，避免 _frames 无限膨胀致 OOM。
        if self._soft_cap_enabled and self._segment_accum >= self.hard_cap_sec:
            _log.info("软封顶硬切: 段长%.0fs 达到上限%.0fs → 强制断句",
                      self._segment_accum, self.hard_cap_sec)
            return True
        # 只要本段出现过有效语音（即使累计不足 min_speech_sec）才允许结束；纯底噪
        # （从无有效语音）_speech_accum==0，不误触发。说完几个字就停的短尾句据此也能
        # 在静音后切段，不再卡在缓冲里需再开口才带出（X-101）。
        if not (self._had_speech or self._speech_accum > 0):
            return False
        # 软封顶日志：刚进入软封顶区间时报告
        if (self._soft_cap_enabled and not self._soft_cap_entered
                and self._segment_accum >= self.soft_cap_sec):
            self._soft_cap_entered = True
            req = self._required_silence_sec()
            steps = int((self._segment_accum - self.soft_cap_sec) / self.soft_cap_step_sec) + 1
            _log.info("软封顶启动(段长%.0fs): 步进%d → 静音要求 %.2fs",
                      self._segment_accum, steps, req)
            self._last_logged_req = req

        # 软封顶日志：所需静音变化时报告（阶梯减半，每步打印一次）
        if self._soft_cap_entered:
            req = self._required_silence_sec()
            if self._last_logged_req is not None and abs(req - self._last_logged_req) > 0.001:
                steps = int((self._segment_accum - self.soft_cap_sec) / self.soft_cap_step_sec) + 1
                _log.info("软封顶步进%d: 段长%.0fs 静音要求→%.2fs",
                          steps, self._segment_accum, req)
                self._last_logged_req = req

        # 连续静音达到（可能被软封顶放宽的）阈值即结束。
        if self._silence_accum >= self._required_silence_sec():
            return True
        return False


class Recorder:
    """录音器，支持可选 VAD：

    - 切换式：提供 on_auto_stop，VAD 检测到段末静音即触发一次结束回调；
    - 连续听写：提供 on_segment，VAD 每检测到一段(语音后1秒静音)即把该段音频
      回调出去并**继续录音**，无需重新触发，直至 stop()。
    on_segment 回调应尽量轻量（如入队），耗时处理交给独立 worker，避免阻塞采集线程。
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE,
                 vad: Optional[SilenceDetector] = None,
                 on_auto_stop: Optional[Callable[[], None]] = None,
                 on_segment: Optional[Callable[[object], None]] = None,
                 denoise=None) -> None:
        """初始化录音器。

        Args:
            sample_rate: 采样率（Hz）
            vad: 静音检测器（可选）
            on_auto_stop: VAD 触发自动停止时回调（切换式）
            on_segment: VAD 切段回调（连续听写）
            denoise: 降噪引擎实例（可选，需实现 process(audio, sr) -> audio）
        """
        self.sample_rate = sample_rate
        self._vad = vad
        self._on_auto_stop = on_auto_stop
        self._on_segment = on_segment
        self._denoise = denoise
        self._stream = None
        self._frames: list = []
        self._recording = False
        self._auto_stopped = False
        if denoise is not None:
            _log.info("降噪引擎已注入录音器: %s", type(denoise).__name__)

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def auto_stopped(self) -> bool:
        """本次录音是否由 VAD 自动结束触发。"""
        return self._auto_stopped

    def start(self) -> None:
        import numpy as np  # 懒加载
        import sounddevice as sd  # 懒加载

        if self._recording:
            return
        self._frames = []
        self._recording = True
        self._auto_stopped = False
        self._denoise_logged = False     # 首帧降噪激活日志标记
        if self._vad is not None:
            self._vad.reset()

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if not self._recording:
                return
            # 降噪预处理：VAD 之前清理环境噪声，降噪后音频同时用于 VAD 与 ASR
            # 异常安全：process() 内部已保证失败时返回原始音频
            audio_frame = indata
            if self._denoise is not None:
                if not self._denoise_logged:
                    _log.info("降噪已激活(首帧): sr=%d 帧长=%d",
                              self.sample_rate, indata.shape[0])
                    self._denoise_logged = True
                try:
                    audio_frame = self._denoise.process(indata, self.sample_rate)
                except Exception:
                    audio_frame = indata
            self._frames.append(audio_frame.copy())
            if self._vad is None or not self._vad.feed(audio_frame):
                return
            # VAD 判定一段语音结束
            if self._on_segment is not None:
                # 连续听写：切出本段，重置 VAD，继续录下一段
                seg = np.concatenate(self._frames, axis=0).flatten()
                speech_sec = self._vad.speech_sec()   # reset 前取本段语音时长
                # 记录本段降噪统计（便于验证降噪效果）
                if self._denoise is not None:
                    try:
                        s = self._denoise.stats
                        _log.info("降噪统计(段): 输入RMS=%.4f 输出RMS=%.4f 抑制=%.1fdB 耗时=%.1fms",
                                  s.input_rms, s.output_rms, s.reduction_db, s.processing_ms)
                    except Exception:
                        pass
                self._frames = []
                self._vad.reset()
                try:
                    self._on_segment(seg, speech_sec)
                except Exception:
                    pass
            elif self._on_auto_stop is not None and not self._auto_stopped:
                # 切换式：仅触发一次结束回调
                self._auto_stopped = True
                try:
                    self._on_auto_stop()
                except Exception:
                    pass

        def _make_stream():
            return sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype="float32",
                callback=callback,
            )

        try:
            try:
                self._stream = _make_stream()
            except (sd.PortAudioError, OSError):
                # macOS AUHAL 音频路由切换后 PortAudio 设备缓存失效（PaErrorCode -9986），
                # 重新初始化强制重新枚举设备，再试一次。
                # _terminate() 可能因 PortAudio 已损坏而失败——忽略，initialize 可能仍能成功。
                try:
                    sd._terminate()
                except Exception:
                    pass
                sd._initialize()
                self._stream = _make_stream()
            self._stream.start()
        except Exception:
            # 启动失败恢复状态，避免实例进入永久不可用状态（_recording=True 死锁）
            self._recording = False
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            raise

    def stop(self):
        """停止并返回 float32 numpy 音频（已展平为一维）。"""
        import numpy as np  # 懒加载

        if not self._recording:
            return np.zeros(0, dtype="float32")
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype="float32")
        audio = np.concatenate(self._frames, axis=0).flatten()
        self._frames = []
        return audio
