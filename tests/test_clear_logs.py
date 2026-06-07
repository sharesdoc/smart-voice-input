"""清除日志：只删本应用日志文件，绝不误删其它文件。"""

from __future__ import annotations

import logging

from voiceinput import logsetup


def test_is_app_log_file_matching():
    ok = ["voiceinput.log", "voiceinput.log.1", "voiceinput.log.99",
          "install.log", "install.log.3"]
    no = ["voiceinput.log.bak", "important.txt", "config.json",
          "voiceinput.logx", "mylog", "voiceinput.log."]
    assert all(logsetup._is_app_log_file(n) for n in ok)
    assert not any(logsetup._is_app_log_file(n) for n in no)


def test_clear_logs_deletes_only_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LOG_DIR", str(tmp_path))
    for n in ("voiceinput.log", "voiceinput.log.1", "install.log"):
        (tmp_path / n).write_text("x")
    keep = {
        "important.txt": "keep",
        "config.json": "{}",
        "voiceinput.log.bak": "weird",     # 不匹配 .N，应保留
    }
    for n, c in keep.items():
        (tmp_path / n).write_text(c)
    (tmp_path / "subdir").mkdir()

    logsetup.setup_logging()
    removed = logsetup.clear_logs()

    assert set(removed) == {"voiceinput.log", "voiceinput.log.1", "install.log"}
    # 非日志一律保留
    for n in keep:
        assert (tmp_path / n).exists()
    assert (tmp_path / "subdir").is_dir()
    # 日志已重建，后续可继续写入
    logging.getLogger("voiceinput").info("after-clear")
    assert (tmp_path / "voiceinput.log").exists()


def test_clear_logs_empty_dir_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LOG_DIR", str(tmp_path))
    logsetup.setup_logging()
    assert logsetup.clear_logs() == []        # 无日志可删，不报错
