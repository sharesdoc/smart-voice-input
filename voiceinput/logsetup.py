"""日志与错误记录 (FR-15)。

滚动日志写入 ~/Library/Logs/VoiceInput/voiceinput.log（可经环境变量覆盖，
便于测试）。提供 get_logger() 供各模块使用。
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

# 本应用日志文件名（含 RotatingFileHandler 的滚动备份 .N）。清除时仅匹配这些，绝不误删其它。
_APP_LOG_BASENAMES = ("voiceinput.log", "install.log")


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


def _is_app_log_file(name: str) -> bool:
    """仅识别本应用日志：voiceinput.log / install.log 及其滚动备份 .N（如 .1/.2/.3）。"""
    for base in _APP_LOG_BASENAMES:
        if name == base or re.fullmatch(re.escape(base) + r"\.\d+", name):
            return True
    return False


def clear_logs() -> list[str]:
    """彻底删除日志目录下本应用的所有日志文件，返回被删文件名列表。

    安全保证（务必只删日志、绝不误删）：
      1) 仅在 log_dir() 目录内操作；
      2) 仅删普通文件，且文件名须精确匹配 voiceinput.log[.N] / install.log[.N]；
      3) 不递归、不碰子目录、不碰任何其它文件。
    先关闭并移除文件 handler 释放 voiceinput.log 句柄，删除后重新挂回，
    使后续日志继续写入新的空文件。
    """
    global _CONFIGURED
    logger = logging.getLogger("voiceinput")
    level = logger.level or logging.INFO

    # 1) 关闭并移除文件 handler，释放对 voiceinput.log 的占用
    for h in list(logger.handlers):
        if isinstance(h, logging.FileHandler):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)

    # 2) 仅删本应用日志文件（精确名匹配）
    removed: list[str] = []
    d = log_dir()
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and not p.is_symlink() and _is_app_log_file(p.name):
                try:
                    p.unlink()
                    removed.append(p.name)
                except Exception:
                    pass

    # 3) 重新挂回文件日志（重建空 voiceinput.log，后续日志照常写入）
    _CONFIGURED = False
    setup_logging(level)
    return removed
