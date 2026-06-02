"""在线 ASR (FR-06)、ASR 工厂 (FR-05/06)、开机自启 (FR-14) 测试。"""

import numpy as np

from voiceinput import autostart
from voiceinput.asr import (
    DashScopeASR,
    MlxWhisperASR,
    OnlineASR,
    SenseVoiceASR,
    WhisperASR,
    make_asr,
)
from voiceinput.config import Config


# ---- ASR 工厂 ----

def test_make_asr_local_default():
    cfg = Config()
    cfg.asr.engine = "whisper_local"
    assert isinstance(make_asr(cfg), WhisperASR)


def test_make_asr_online():
    cfg = Config()
    cfg.asr.engine = "online"
    asr = make_asr(cfg)
    assert isinstance(asr, OnlineASR)
    assert asr.model == "whisper-1"


def test_make_asr_sensevoice():
    cfg = Config()
    cfg.asr.engine = "sensevoice"
    asr = make_asr(cfg)
    assert isinstance(asr, SenseVoiceASR)
    assert "SenseVoice" in asr.model_name


def test_sensevoice_language_normalization():
    assert SenseVoiceASR(language="zh").language == "zh"
    assert SenseVoiceASR(language="en").language == "en"
    assert SenseVoiceASR(language="xx").language == "auto"  # 未知语言回退 auto


def test_sensevoice_empty_audio():
    assert SenseVoiceASR().transcribe([]) == ""
    assert SenseVoiceASR().transcribe(None) == ""


def test_make_asr_dashscope():
    cfg = Config()
    cfg.asr.engine = "dashscope"
    asr = make_asr(cfg)
    assert isinstance(asr, DashScopeASR)
    assert asr.model == "paraformer-realtime-v2"


def test_dashscope_empty_audio():
    assert DashScopeASR().transcribe([]) == ""
    assert DashScopeASR().transcribe(None) == ""


def test_make_asr_mlx_whisper():
    cfg = Config()
    cfg.asr.engine = "mlx_whisper"
    asr = make_asr(cfg)
    assert isinstance(asr, MlxWhisperASR)
    assert "whisper" in asr.model


def test_mlx_chinese_simplified_prompt():
    from voiceinput.asr import _ZH_SIMPLIFIED_PROMPT
    assert MlxWhisperASR(language="zh").initial_prompt == _ZH_SIMPLIFIED_PROMPT
    assert MlxWhisperASR(language="en").initial_prompt is None


def test_mlx_empty_audio():
    assert MlxWhisperASR().transcribe([]) == ""
    assert MlxWhisperASR().transcribe(None) == ""


# ---- 在线 ASR ----

class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.captured = None

    def post(self, url, headers=None, data=None, files=None):
        self.captured = {"url": url, "data": data, "files": files}
        return FakeResp({"text": self.text})

    def close(self):
        pass


def test_online_asr_transcribe():
    asr = OnlineASR(base_url="https://api.openai.com/v1", language="zh")
    audio = (np.random.RandomState(0).randn(16000) * 0.1).astype("float32")
    client = FakeClient("识别出的文本")
    text = asr.transcribe(audio, client=client)
    assert text == "识别出的文本"
    assert client.captured["url"].endswith("/audio/transcriptions")
    assert client.captured["data"]["model"] == "whisper-1"
    assert "file" in client.captured["files"]


def test_online_asr_empty_audio():
    asr = OnlineASR(base_url="x")
    assert asr.transcribe(np.zeros(0, dtype="float32")) == ""


def test_online_asr_wav_encoding():
    """WAV 编码应为合法 RIFF 头。"""
    asr = OnlineASR(base_url="x")
    audio = np.array([0.0, 0.5, -0.5, 1.0], dtype="float32")
    wav = asr._encode_wav(audio)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"


# ---- 开机自启 ----

def test_build_plist_contains_module():
    plist = autostart.build_plist(python_exe="/usr/bin/python3")
    assert "com.voiceinput.agent" in plist
    assert "voiceinput" in plist
    assert "/usr/bin/python3" in plist
    assert "RunAtLoad" in plist


def test_enable_disable_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LAUNCHAGENTS_DIR", str(tmp_path))
    assert autostart.is_enabled() is False
    assert autostart.enable(python_exe="/usr/bin/python3") is True
    assert autostart.is_enabled() is True
    assert (tmp_path / "com.voiceinput.agent.plist").exists()
    assert autostart.disable() is True
    assert autostart.is_enabled() is False
