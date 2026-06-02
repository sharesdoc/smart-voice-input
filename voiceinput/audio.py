"""麦克风录音封装 + 静音自动断句 (FR-03/FR-04)。

使用 sounddevice 采集 16kHz 单声道 PCM（Whisper 所需），懒加载依赖。
提供切换式录音：start() 开始，stop() 返回 float32 numpy 音频；
可选 VAD：检测到一段语音后持续静音超过阈值即触发自动结束回调。

SilenceDetector 为纯逻辑（喂入音频块返回是否应结束），便于单测。
"""

from __future__ import annotations

import math
from typing import Callable, Optional

SAMPLE_RATE = 16000
CHANNELS = 1


def rms(chunk) -> float:
    """计算音频块的均方根能量。接受 numpy 数组或可迭代序列。"""
    import numpy as np

    arr = np.asarray(chunk, dtype="float32").flatten()
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))


class SilenceDetector:
    """静音自动断句判定 (FR-04)，纯逻辑。

    规则：先要累计检测到 >= min_speech_sec 的语音（避免开头静音即结束）；
    此后若连续静音时长 >= silence_sec，则 feed() 返回 True 表示应结束。
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        silence_threshold: float = 0.01,
        silence_sec: float = 1.2,
        min_speech_sec: float = 0.3,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self._speech_accum = 0.0   # 已累计语音时长
        self._silence_accum = 0.0  # 当前连续静音时长
        self._had_speech = False

    def reset(self) -> None:
        self._speech_accum = 0.0
        self._silence_accum = 0.0
        self._had_speech = False

    def feed(self, chunk) -> bool:
        """喂入一块音频，返回是否应结束录音。"""
        n = len(chunk)
        if n == 0:
            return False
        dur = n / self.sample_rate
        if rms(chunk) >= self.silence_threshold:
            # 语音
            self._speech_accum += dur
            self._silence_accum = 0.0
            if self._speech_accum >= self.min_speech_sec:
                self._had_speech = True
        else:
            # 静音
            self._silence_accum += dur
            if self._had_speech and self._silence_accum >= self.silence_sec:
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
                 on_segment: Optional[Callable[[object], None]] = None) -> None:
        self.sample_rate = sample_rate
        self._vad = vad
        self._on_auto_stop = on_auto_stop
        self._on_segment = on_segment
        self._stream = None
        self._frames: list = []
        self._recording = False
        self._auto_stopped = False

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
        if self._vad is not None:
            self._vad.reset()

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if not self._recording:
                return
            self._frames.append(indata.copy())
            if self._vad is None or not self._vad.feed(indata):
                return
            # VAD 判定一段语音结束
            if self._on_segment is not None:
                # 连续听写：切出本段，重置 VAD，继续录下一段
                seg = np.concatenate(self._frames, axis=0).flatten()
                self._frames = []
                self._vad.reset()
                try:
                    self._on_segment(seg)
                except Exception:
                    pass
            elif self._on_auto_stop is not None and not self._auto_stopped:
                # 切换式：仅触发一次结束回调
                self._auto_stopped = True
                try:
                    self._on_auto_stop()
                except Exception:
                    pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()

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
