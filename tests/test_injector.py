"""注入器 inject_method 分发测试 (J-P1-01: keystroke 支持)。

仅验证「按 method 选择 paste/keystroke 路径」的分发逻辑，不真正发系统事件
（_type_paste/_type_keystroke 经 monkeypatch 拦截）。MacInjector 仅 macOS 可构造，
故非 Darwin 跳过。
"""

import platform

import pytest

from voiceinput.injector import MacInjector, make_injector

_skip_non_mac = pytest.mark.skipif(
    platform.system() != "Darwin", reason="MacInjector 仅 macOS 可构造"
)


@_skip_non_mac
def test_make_injector_default_is_paste():
    inj = make_injector()
    assert inj.method == "paste"


@_skip_non_mac
def test_make_injector_keystroke():
    inj = make_injector("keystroke")
    assert inj.method == "keystroke"


@_skip_non_mac
def test_invalid_method_falls_back_to_paste():
    inj = MacInjector(method="bogus")
    assert inj.method == "paste"


@_skip_non_mac
def test_type_text_dispatches_keystroke(monkeypatch):
    inj = make_injector("keystroke")
    calls = []
    monkeypatch.setattr(inj, "_type_keystroke", lambda t: calls.append(("ks", t)))
    monkeypatch.setattr(inj, "_type_paste",
                        lambda t, **k: calls.append(("paste", t)))
    inj.type_text("你好")
    assert calls == [("ks", "你好")]


@_skip_non_mac
def test_type_text_dispatches_paste(monkeypatch):
    inj = make_injector("paste")
    calls = []
    monkeypatch.setattr(inj, "_type_keystroke", lambda t: calls.append(("ks", t)))
    monkeypatch.setattr(inj, "_type_paste",
                        lambda t, **k: calls.append(("paste", t)))
    inj.type_text("hello")
    assert calls == [("paste", "hello")]


@_skip_non_mac
def test_empty_text_no_dispatch(monkeypatch):
    inj = make_injector("keystroke")
    calls = []
    monkeypatch.setattr(inj, "_type_keystroke", lambda t: calls.append(t))
    inj.type_text("")
    assert calls == []
