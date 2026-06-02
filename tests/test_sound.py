"""提示音 play_sound 接线测试 (J-P1-01)。

验证 general.play_sound 配置真正控制提示音播放，且失败被吞掉不抛出。
VoiceInputApp 构造不导入 rumps，可在无 GUI 环境测试；afplay 经 monkeypatch 拦截。
"""

import voiceinput.app as appmod
from voiceinput.app import VoiceInputApp
from voiceinput.config import Config


def test_play_sound_enabled_invokes_player(monkeypatch):
    """play_sound=True 时应调用 afplay 播放系统音效。"""
    called = []
    monkeypatch.setattr(appmod, "_afplay", lambda p: called.append(p))
    cfg = Config()
    cfg.general.play_sound = True
    app = VoiceInputApp(cfg=cfg)
    app._play_start_sound()
    assert called == [appmod._START_SOUND]


def test_play_sound_disabled_skips_player(monkeypatch):
    """play_sound=False 时不应调用 afplay。"""
    called = []
    monkeypatch.setattr(appmod, "_afplay", lambda p: called.append(p))
    cfg = Config()
    cfg.general.play_sound = False
    app = VoiceInputApp(cfg=cfg)
    app._play_start_sound()
    assert called == []


def test_play_sound_swallows_player_error(monkeypatch):
    """播放器抛错时 _play_start_sound 不应向上抛出（不阻断听写）。"""
    def boom(_p):
        raise RuntimeError("no audio device")

    monkeypatch.setattr(appmod, "_afplay", boom)
    cfg = Config()
    cfg.general.play_sound = True
    app = VoiceInputApp(cfg=cfg)
    app._play_start_sound()  # 不应抛错
