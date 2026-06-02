"""双击停止时的协作式取消测试。

验证：取消后 Pipeline 不再向输入框注入（丢弃本段）；app 停止连续听写时
会清空待处理队列并取消当前流水线。
"""

import queue

from voiceinput.app import VoiceInputApp
from voiceinput.config import Config
from voiceinput.pipeline import Pipeline


class SpyInjector:
    def __init__(self):
        self.typed = []

    def type_text(self, text):
        self.typed.append(text)


def _raw_cfg():
    cfg = Config()
    cfg.llm.mode = "off"          # 纯转写，避免网络
    cfg.postprocess.mode = "raw"
    return cfg


def test_cancel_before_run_skips_injection():
    inj = SpyInjector()
    p = Pipeline(cfg=_raw_cfg(), injector=inj, transcribe_fn=lambda a: "你好世界")
    p.cancel()
    r = p.run([0.0] * 1600)
    assert inj.typed == []          # 未注入
    assert r.aborted is True
    assert r.final_text == ""


def test_cancel_during_asr_skips_injection():
    inj = SpyInjector()
    p = Pipeline(cfg=_raw_cfg(), injector=inj, transcribe_fn=None)

    def transcribe(_audio):
        p.cancel()                  # 模拟识别期间用户双击停止
        return "迟到的文本"

    p.transcribe_fn = transcribe
    r = p.run([0.0] * 1600)
    assert inj.typed == []          # 识别后取消 → 不注入
    assert r.aborted is True


def test_not_cancelled_injects_normally():
    inj = SpyInjector()
    p = Pipeline(cfg=_raw_cfg(), injector=inj, transcribe_fn=lambda a: "正常文本")
    r = p.run([0.0] * 1600)
    assert inj.typed == ["正常文本"]
    assert r.final_text == "正常文本"
    assert r.aborted is False


def test_drain_queue_empties_pending():
    q = queue.Queue()
    for i in range(5):
        q.put(f"seg{i}")
    VoiceInputApp._drain_queue(q)
    assert q.qsize() == 0


def test_stop_continuous_cancels_current_pipeline():
    app = VoiceInputApp(cfg=_raw_cfg())
    app._continuous_active = True
    app._seg_queue = queue.Queue()
    for i in range(3):
        app._seg_queue.put(f"seg{i}")   # 模拟排队中的段

    inj = SpyInjector()
    cur = Pipeline(cfg=_raw_cfg(), injector=inj, transcribe_fn=lambda a: "x")
    cur.run([0.0] * 1600)               # 先建立 session
    app._current_pipeline = cur

    class _Rec:
        def stop(self):
            return None

    app._recorder = _Rec()
    app._stop_continuous()

    assert cur._cancelled is True       # 当前流水线已被取消
    # 队列被清空（除唤醒哨兵 None 外无残留待处理段）
    drained = []
    try:
        while True:
            drained.append(app._seg_queue.get_nowait())
    except queue.Empty:
        pass
    assert all(x is None for x in drained)  # 只剩 None 哨兵
