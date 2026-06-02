"""无障碍标签 _set_a11y 测试 (J-P3-02)。

settings_ui 模块级不导入 AppKit（懒加载于函数内），故可跨平台导入测试。
用假控件验证 setAccessibilityLabel_ 的调用与容错，无需真实 GUI。
"""

from voiceinput.settings_ui import _set_a11y


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
