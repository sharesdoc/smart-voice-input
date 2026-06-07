"""连续听写、语言切换、宽松状态流转测试 (FR-03/语言)。"""

import queue
import threading

import voiceinput.app as appmod
from voiceinput.app import VoiceInputApp
from voiceinput.config import Config, load_config
from voiceinput.state import AppState, StateMachine


# ---- 宽松状态流转（连续听写场景） ----

def test_set_state_lenient_inject_to_listening():
    sm = StateMachine()
    sm.transition(AppState.LISTENING)
    sm.transition(AppState.TRANSCRIBING)
    sm.transition(AppState.INJECTING)
    # 严格迁移不允许 INJECTING->LISTENING，但 set_state 宽松允许
    sm.set_state(AppState.LISTENING)
    assert sm.state == AppState.LISTENING


def test_set_state_callback_fires():
    seen = []
    sm = StateMachine(on_change=lambda o, n: seen.append((o, n)))
    sm.set_state(AppState.LISTENING)
    assert seen == [(AppState.IDLE, AppState.LISTENING)]


# ---- 语言 / 连续听写 设置 ----

def test_apply_language_persists_and_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app._asr = object()  # 假装已缓存
    app.apply_language("en")
    assert app.cfg.general.language == "en"
    assert app._asr is None  # 缓存失效，按新语言重建
    assert load_config().general.language == "en"


def test_apply_continuous_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_CONFIG_DIR", str(tmp_path))
    app = VoiceInputApp(cfg=Config())
    app.apply_continuous(False)
    assert load_config().general.continuous_dictation is False


def test_continuous_default_on():
    assert Config().general.continuous_dictation is True


# ---- 连续听写：分段 worker 顺序处理并注入 ----

class FakeInjector:
    def __init__(self):
        self.buffer = ""

    def type_text(self, text):
        self.buffer += text

    def delete_chars(self, n, method="backspace"):
        if n > 0:
            self.buffer = self.buffer[:-n]


class FakeASR:
    def transcribe(self, seg):
        return seg  # 段内容即“识别文本”，便于断言


def test_segment_worker_processes_in_order(monkeypatch):
    cfg = Config()
    cfg.llm.mode = "off"  # 纯转写，避免网络
    app = VoiceInputApp(cfg=cfg)

    fake_inj = FakeInjector()
    monkeypatch.setattr(appmod, "make_injector", lambda *a, **k: fake_inj)
    monkeypatch.setattr(app, "_get_asr", lambda: FakeASR())

    app._continuous_active = True
    app._seg_queue = queue.Queue()
    app._stop_worker = threading.Event()

    # 入队三段语音 + 结束哨兵（队列项为 (段, VAD语音时长) 元组，与生产一致）
    for seg in ("第一段", "第二段", "第三段"):
        app._seg_queue.put((seg, 1.0))
    app._seg_queue.put(None)

    app._segment_worker()  # 同步跑到 None 退出

    # 三段按顺序注入，连成一串
    assert fake_inj.buffer == "第一段第二段第三段"
