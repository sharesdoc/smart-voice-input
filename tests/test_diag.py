"""稳定性诊断日志测试：自重复检测 + 跨段重复监控。"""

from voiceinput.diag import OutputMonitor, _is_self_doubled


def test_self_doubled_exact():
    assert _is_self_doubled("今天天气不错今天天气不错") is True


def test_self_doubled_with_separator():
    assert _is_self_doubled("今天天气不错，今天天气不错") is True


def test_not_doubled_normal():
    assert _is_self_doubled("今天天气不错我们出去走走") is False


def test_not_doubled_short_repeat():
    # 短重复(如叠词)不算"整句两遍"
    assert _is_self_doubled("好好") is False
    assert _is_self_doubled("谢谢谢谢") is False


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _warnings(monitor):
    # 收集 monitor 写出的 warning（通过替换 logger）
    pass


def test_monitor_flags_cross_segment_duplicate():
    clock = _Clock()
    m = OutputMonitor(window_sec=8.0, clock=clock)
    msgs = []
    m._log = type("L", (), {
        "info": lambda self, *a: None,
        "warning": lambda self, *a: msgs.append(a[0] % a[1:] if len(a) > 1 else a[0]),
    })()
    m.record("这是一段完整的话")
    clock.t = 2.0
    m.record("这是一段完整的话")          # 2s 后重复 → 应告警
    assert any("疑似重复输出" in s for s in msgs)


def test_monitor_no_flag_outside_window():
    clock = _Clock()
    m = OutputMonitor(window_sec=8.0, clock=clock)
    msgs = []
    m._log = type("L", (), {
        "info": lambda self, *a: None,
        "warning": lambda self, *a: msgs.append(a[0]),
    })()
    m.record("这是一段完整的话")
    clock.t = 20.0                       # 超出窗口
    m.record("这是一段完整的话")
    assert not any("疑似重复输出" in str(s) for s in msgs)


def test_monitor_ignores_empty():
    m = OutputMonitor()
    m.record("")                          # 不应抛错
    m.record(None)
