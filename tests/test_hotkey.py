"""双击 Command 检测逻辑测试 (FR-03)。"""

from voiceinput.hotkey import DoubleTapDetector


def tap(det: DoubleTapDetector, t: float) -> bool:
    """模拟一次干净的 Command 点按（按下后抬起，无其他键）。"""
    det.on_command_down(t)
    return det.on_command_up(t + 0.01)


def test_single_tap_not_triggered():
    det = DoubleTapDetector(double_tap_ms=300)
    assert tap(det, 0.0) is False


def test_double_tap_within_threshold():
    det = DoubleTapDetector(double_tap_ms=300)
    assert tap(det, 0.0) is False
    assert tap(det, 0.20) is True  # 200ms < 300ms


def test_double_tap_too_slow_not_triggered():
    det = DoubleTapDetector(double_tap_ms=300)
    assert tap(det, 0.0) is False
    assert tap(det, 0.50) is False  # 500ms > 300ms


def test_command_combo_not_counted_as_tap():
    """⌘+C 这类组合键不应算作 tap。"""
    det = DoubleTapDetector(double_tap_ms=300)
    det.on_command_down(0.0)
    det.on_other_key(0.01)        # 期间按了其他键
    assert det.on_command_up(0.02) is False
    # 紧接着一次干净点按也不应触发双击（组合键打断了计时）
    assert tap(det, 0.05) is False


def test_combo_then_two_clean_taps_triggers():
    det = DoubleTapDetector(double_tap_ms=300)
    det.on_command_down(0.0)
    det.on_other_key(0.01)
    det.on_command_up(0.02)       # 组合键，不计
    assert tap(det, 0.10) is False  # 第一次干净 tap
    assert tap(det, 0.25) is True   # 第二次干净 tap，间隔150ms


def test_triple_tap_only_one_double():
    """三连击只触发一次双击（消费后重置）。"""
    det = DoubleTapDetector(double_tap_ms=300)
    assert tap(det, 0.0) is False
    assert tap(det, 0.10) is True   # 双击
    assert tap(det, 0.20) is False  # 第三次成为新的第一次
    assert tap(det, 0.30) is True   # 与第三次构成新双击
