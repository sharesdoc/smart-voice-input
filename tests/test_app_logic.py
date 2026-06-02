"""应用层逻辑测试（不进入 rumps 事件循环）。

VoiceInputApp 构造不导入 rumps（懒加载于 build()），故可在无 GUI 环境测试。
"""

from voiceinput.app import VoiceInputApp
from voiceinput.config import Config
from voiceinput.state import AppState


def _drive_to_refining(app: VoiceInputApp):
    app._sm.transition(AppState.LISTENING)
    app._sm.transition(AppState.TRANSCRIBING)
    app._sm.transition(AppState.REFINING)


def test_set_state_idle_uses_force():
    """pipeline 回调 'IDLE' 应能从任意状态强制回到空闲。"""
    app = VoiceInputApp(cfg=Config())
    _drive_to_refining(app)
    app._set_state("IDLE")
    assert app._sm.state == AppState.IDLE
