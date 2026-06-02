"""日志模块测试 (FR-15)。"""

import logging

from voiceinput import logsetup


def test_log_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LOG_DIR", str(tmp_path))
    assert logsetup.log_dir() == tmp_path


def test_setup_logging_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LOG_DIR", str(tmp_path))
    # 重置幂等标记，确保本次真正配置
    monkeypatch.setattr(logsetup, "_CONFIGURED", False)
    logger = logsetup.setup_logging(level=logging.INFO)
    logger.info("测试日志条目")
    for h in logger.handlers:
        h.flush()
    log_file = tmp_path / "voiceinput.log"
    assert log_file.exists()
    assert "测试日志条目" in log_file.read_text(encoding="utf-8")


def test_setup_logging_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEINPUT_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(logsetup, "_CONFIGURED", False)
    l1 = logsetup.setup_logging()
    n1 = len(l1.handlers)
    l2 = logsetup.setup_logging()
    assert len(l2.handlers) == n1  # 不重复添加处理器
