"""日志与错误记录 (FR-15)。

滚动日志写入 ~/Library/Logs/VoiceInput/voiceinput.log（可经环境变量覆盖，
便于测试）。提供 get_logger() 供各模块使用。
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def log_dir() -> Path:
    override = os.environ.get("VOICEINPUT_LOG_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Logs" / "VoiceInput"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根日志（幂等）。返回应用 logger。"""
    global _CONFIGURED
    logger = logging.getLogger("voiceinput")
    if _CONFIGURED:
        return logger
    logger.setLevel(level)
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            d / "voiceinput.log", maxBytes=1_000_000, backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    except Exception:
        # 日志不可写不应阻断程序（NFR-04）
        logger.addHandler(logging.NullHandler())
    _CONFIGURED = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("voiceinput")
