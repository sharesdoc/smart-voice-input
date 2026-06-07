"""无障碍标签 _set_a11y 测试 (J-P3-02)。

settings_ui 模块级不导入 AppKit（懒加载于函数内），故可跨平台导入测试。
用假控件验证 setAccessibilityLabel_ 的调用与容错，无需真实 GUI。
"""

from voiceinput.config import DEFAULT_OLLAMA_MODEL
from voiceinput.settings_ui import _ollama_model_options, _set_a11y, _set_control_enabled


class FakeControl:
    def __init__(self):
        self.a11y = None

    def setAccessibilityLabel_(self, label):
        self.a11y = label


class NoA11yControl:
    """不支持无障碍 API 的控件——调用应被静默吞掉。"""


def test_set_a11y_assigns_label():
    c = FakeControl()
    _set_a11y(c, "语音识别引擎")
    assert c.a11y == "语音识别引擎"


def test_set_a11y_empty_label_skips():
    c = FakeControl()
    _set_a11y(c, "")
    assert c.a11y is None


def test_set_a11y_swallows_unsupported_control():
    c = NoA11yControl()
    # 不应抛 AttributeError
    _set_a11y(c, "标签")


def test_set_a11y_swallows_setter_error():
    class Boom:
        def setAccessibilityLabel_(self, _label):
            raise RuntimeError("no a11y backend")

    _set_a11y(Boom(), "标签")  # 不应抛错


def test_set_control_enabled_uses_native_set_enabled():
    class NativeControl:
        def __init__(self):
            self.enabled = None

        def setEnabled_(self, enabled):
            self.enabled = enabled

    c = NativeControl()
    _set_control_enabled(c, False)
    assert c.enabled is False


def test_set_control_enabled_supports_scroll_text_view():
    class TextView:
        def __init__(self):
            self.editable = None
            self.selectable = None

        def setEditable_(self, enabled):
            self.editable = enabled

        def setSelectable_(self, enabled):
            self.selectable = enabled

    class ScrollView:
        def __init__(self):
            self.doc = TextView()

        def documentView(self):
            return self.doc

    c = ScrollView()
    _set_control_enabled(c, False)
    assert c.doc.editable is False
    assert c.doc.selectable is True


def test_set_control_enabled_swallows_unsupported_control():
    _set_control_enabled(object(), False)  # 不应抛 AttributeError


def test_ollama_model_options_keeps_current_when_missing():
    opts = _ollama_model_options([], DEFAULT_OLLAMA_MODEL)
    assert opts[0] == DEFAULT_OLLAMA_MODEL
    assert "(未检测到 / none)" in opts


def test_ollama_model_options_does_not_duplicate_current():
    opts = _ollama_model_options([DEFAULT_OLLAMA_MODEL, "qwen3:8b"], DEFAULT_OLLAMA_MODEL)
    assert opts == [DEFAULT_OLLAMA_MODEL, "qwen3:8b"]
