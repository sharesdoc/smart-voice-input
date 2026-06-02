"""稳定性诊断日志：记录每段语音输出并检测疑似重复。

目的：把"软件每段实际输出了什么 + 有没有重复"写进日志，便于事后分析稳定性/定位 bug。
检测两类重复：
- 跨段重复：本段输出与最近若干秒内某一段完全相同（疑似分段/模型/注入重复）。
- 单段内自重复：单段文本本身是"同一句说了两遍"（X 或 X<标点>X）。

纯逻辑(_is_self_doubled)可单测；OutputMonitor 维护跨段历史并写日志，时钟可注入便于测试。
"""

from __future__ import annotations

import time

from .logsetup import get_logger


def _clip(text: str, n: int = 80) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + "…"


def _is_self_doubled(text: str, min_half: int = 6) -> bool:
    """文本是否为"同一段重复两遍"：X+X 或 X+<标点/空白>+X（X 长度≥min_half）。"""
    t = (text or "").strip()
    n = len(t)
    if n < 2 * min_half:
        return False
    if n % 2 == 0 and t[: n // 2] == t[n // 2:]:
        return True
    for sep in (1, 2):                      # 中间可有 1-2 个标点/空白分隔
        if (n - sep) % 2 != 0:
            continue
        half = (n - sep) // 2
        if half < min_half:
            continue
        mid = t[half: half + sep]
        if t[:half] == t[half + sep:] and all(not ch.isalnum() for ch in mid):
            return True
    return False


class OutputMonitor:
    """跨段输出监控：记录每段输出、标记疑似重复，全部写入日志。"""

    def __init__(self, window_sec: float = 8.0, keep: int = 6, clock=None) -> None:
        self._log = get_logger()
        self.window_sec = window_sec
        self.keep = keep
        self._clock = clock or time.monotonic
        self._history: list[tuple[float, str]] = []  # [(ts, text)]

    def record(self, text: str) -> None:
        """登记一段实际输出文本，写日志并检测重复。空文本忽略。"""
        text = (text or "").strip()
        if not text:
            return
        now = self._clock()

        dup_prev = None
        for ts, prev in self._history:
            if now - ts <= self.window_sec and prev == text:
                dup_prev = now - ts
                break

        self._log.info("📤 本段输出 %d字: %r", len(text), _clip(text))
        if dup_prev is not None:
            self._log.warning(
                "⚠ 疑似重复输出：本段与 %.1fs 前一段完全相同 → %r", dup_prev, _clip(text))
        if _is_self_doubled(text):
            self._log.warning("⚠ 疑似单段内重复(同一句两遍): %r", _clip(text))

        self._history.append((now, text))
        if len(self._history) > self.keep:
            self._history = self._history[-self.keep:]
