"""强制过滤命中历史（从运行日志中筛取，不另存文件）。

pipeline 每次命中强制过滤都会记一行
"  (强制过滤命中: '...'，跳过注入)"。
本模块只做一件事：扫日志、抽出这类行、解析成结构化记录，
供设置页「历史记录」按钮展示。
"""

from __future__ import annotations

import re
from pathlib import Path

from .logsetup import log_dir

# 必须与 pipeline.run 写入的日志格式保持一致。样例：
#   2026-06-06 15:30:00,123 [INFO] voiceinput:   (强制过滤命中: 'Yeah.'，跳过注入)
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*?"
    r"\(强制过滤命中: '(?P<text>.*?)'，跳过注入\)\s*$"
)


def _log_files() -> list[Path]:
    """当前日志 + 滚动备份，按从旧到新返回。"""
    d = log_dir()
    files: list[Path] = []
    for i in (3, 2, 1):
        p = d / f"voiceinput.log.{i}"
        if p.exists():
            files.append(p)
    base = d / "voiceinput.log"
    if base.exists():
        files.append(base)
    return files


def load(limit: int = 1000) -> list[dict]:
    """扫描日志，返回强制过滤命中记录（最新在前，最多 limit 条）。

    每条字段：ts(时间字符串)、text(被拦内容)。
    """
    recs: list[dict] = []
    for p in _log_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ln in text.splitlines():
            m = _LINE.search(ln)
            if not m:
                continue
            recs.append({
                "ts": m.group("ts"),
                "text": m.group("text"),
            })
    recs.reverse()
    return recs[:limit]
