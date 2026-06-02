"""状态机测试 (§7)。"""

import pytest

from voiceinput.state import AppState, IllegalTransition, StateMachine


def test_initial_idle():
    sm = StateMachine()
    assert sm.state == AppState.IDLE


def test_valid_flow():
    sm = StateMachine()
    sm.transition(AppState.LISTENING)
    sm.transition(AppState.TRANSCRIBING)
    sm.transition(AppState.REFINING)
    sm.transition(AppState.REWRITING)
    assert sm.state == AppState.REWRITING


def test_illegal_transition_raises():
    sm = StateMachine()
    with pytest.raises(IllegalTransition):
        sm.transition(AppState.REWRITING)  # IDLE 不能直接到 REWRITING


def test_force_idle_from_any():
    sm = StateMachine()
    sm.transition(AppState.LISTENING)
    sm.transition(AppState.TRANSCRIBING)
    sm.force_idle()
    assert sm.state == AppState.IDLE


def test_on_change_callback():
    seen = []
    sm = StateMachine(on_change=lambda o, n: seen.append((o, n)))
    sm.transition(AppState.LISTENING)
    assert seen == [(AppState.IDLE, AppState.LISTENING)]


def test_same_state_noop():
    seen = []
    sm = StateMachine(on_change=lambda o, n: seen.append((o, n)))
    sm.transition(AppState.IDLE)  # 已是 IDLE
    assert seen == []


def test_every_state_has_icon():
    for s in AppState:
        assert isinstance(s.icon, str) and s.icon
