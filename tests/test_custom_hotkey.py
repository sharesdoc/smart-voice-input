"""自定义热键解析与匹配逻辑测试 (J-P1-01: custom_hotkey)。

纯逻辑（parse_combo / HotkeyMatcher / IMPLEMENTED_TRIGGERS），无 pynput 依赖。
"""

from voiceinput.hotkey import (
    IMPLEMENTED_TRIGGERS,
    HotkeyMatcher,
    parse_combo,
)


def test_parse_combo_basic():
    assert parse_combo("ctrl+option+space") == frozenset({"ctrl", "alt", "space"})


def test_parse_combo_aliases():
    assert parse_combo("command+Shift+A") == frozenset({"cmd", "shift", "a"})
    assert parse_combo("control+opt+x") == frozenset({"ctrl", "alt", "x"})


def test_parse_combo_empty_and_whitespace():
    assert parse_combo("") == frozenset()
    assert parse_combo("  ctrl + + space ") == frozenset({"ctrl", "space"})


def test_matcher_fires_once_when_complete():
    m = HotkeyMatcher(parse_combo("ctrl+alt+space"))
    assert m.press("ctrl") is False
    assert m.press("alt") is False
    assert m.press("space") is True       # 组合完整 → 触发
    assert m.press("space") is False      # 不重复触发（仍按住）


def test_matcher_rearms_after_release():
    m = HotkeyMatcher(parse_combo("ctrl+space"))
    assert m.press("ctrl") is False
    assert m.press("space") is True
    m.release("space")                    # 松开一个组合键 → 重新武装
    assert m.press("space") is True       # 再次完整 → 再次触发


def test_matcher_partial_never_fires():
    m = HotkeyMatcher(parse_combo("ctrl+alt+space"))
    assert m.press("ctrl") is False
    assert m.press("space") is False      # 缺 alt，不触发
    m.release("ctrl")
    assert m.press("alt") is False


def test_matcher_extra_keys_dont_break():
    m = HotkeyMatcher(parse_combo("ctrl+space"))
    m.press("shift")                      # 多余键不影响
    assert m.press("ctrl") is False
    assert m.press("space") is True


def test_empty_combo_never_fires():
    m = HotkeyMatcher(parse_combo(""))
    assert m.press("ctrl") is False
    assert m.press("space") is False


def test_implemented_triggers():
    assert "double_command" in IMPLEMENTED_TRIGGERS
    assert "custom_hotkey" in IMPLEMENTED_TRIGGERS
    assert "push_to_talk" not in IMPLEMENTED_TRIGGERS  # 暂未实现
