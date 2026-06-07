"""底噪幻觉拦截历史：从运行日志筛取拦截行（新格式按语音时长，兼容旧段长格式）。"""

from __future__ import annotations

from voiceinput import noise_history

# 新格式（语音时长判定）
_NEW1 = (
    "2026-06-06 18:22:22,336 [INFO] voiceinput:   "
    "(疑似底噪幻觉，跳过): 语音0.05s 段长7.3s 2字 '嗯。' (需≥0.14s)"
)
_NEW2 = (
    "2026-06-06 18:23:11,084 [INFO] voiceinput:   "
    "(疑似底噪幻觉，跳过): 语音0.03s 段长2.5s 1字 '我' (需≥0.08s)"
)
# 旧格式（段长判定，应仍能解析，voiced=None）
_OLD = (
    "2026-06-05 10:00:00,000 [INFO] voiceinput:   "
    "(疑似底噪幻觉，跳过): 段长1.8s 2字 '嗯。' (上限1.5s)"
)
_OTHER = "2026-06-06 18:22:30,000 [INFO] voiceinput: ▶ 处理语音段: 样本=12345"


def test_parses_new_format(monkeypatch, tmp_path):
    (tmp_path / "voiceinput.log").write_text(
        "\n".join([_NEW1, _OTHER, _NEW2]) + "\n", encoding="utf-8")
    monkeypatch.setattr(noise_history, "log_dir", lambda: tmp_path)
    recs = noise_history.load()
    assert len(recs) == 2                       # 只取拦截行
    assert recs[0]["text"] == "我"               # 最新在前
    assert recs[0]["voiced"] == 0.03 and recs[0]["seg"] == 2.5 and recs[0]["chars"] == 1
    assert recs[1]["text"] == "嗯。" and recs[1]["voiced"] == 0.05


def test_parses_old_format_voiced_none(monkeypatch, tmp_path):
    (tmp_path / "voiceinput.log").write_text(_OLD + "\n", encoding="utf-8")
    monkeypatch.setattr(noise_history, "log_dir", lambda: tmp_path)
    recs = noise_history.load()
    assert len(recs) == 1
    assert recs[0]["voiced"] is None and recs[0]["seg"] == 1.8 and recs[0]["text"] == "嗯。"


def test_missing_log_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(noise_history, "log_dir", lambda: tmp_path)
    assert noise_history.load() == []


def test_reads_rotated_files_newest_first(monkeypatch, tmp_path):
    (tmp_path / "voiceinput.log.1").write_text(_OLD + "\n", encoding="utf-8")
    (tmp_path / "voiceinput.log").write_text(_NEW2 + "\n", encoding="utf-8")
    monkeypatch.setattr(noise_history, "log_dir", lambda: tmp_path)
    recs = noise_history.load()
    assert [r["text"] for r in recs] == ["我", "嗯。"]   # 当前日志(新)在前，备份(旧)在后

def test_force_filter_history_load_smoke():
    """force_filter_history.load() 不崩溃且返回列表。"""
    from voiceinput.force_filter_history import load
    recs = load()
    assert isinstance(recs, list)
