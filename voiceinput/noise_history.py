"""底噪幻觉拦截历史（从运行日志中筛取，不另存文件）。

拦截事件本就写在运行日志里——pipeline 每次拦截都会记一行
"(疑似底噪幻觉，跳过): 语音Xs 段长Ys N字 '…' (需≥Zs)"。本模块只做一件事：
扫描日志文件、**只**抽出这一类行，解析成结构化记录（时间/语音时长/段长/字数/内容），
供设置页「拦截历史」按钮展示。其余日志一律不取。

兼容旧格式 "(…): 段长Ys N字 '…' (上限Zs)"（无语音时长字段，voiced 记为 None），
以便历史记录跨格式变更仍可查看。
"""

from __future__ import annotations

import re
from pathlib import Path

from .logsetup import log_dir

# 新格式（按语音时长判定）。须与 pipeline.run 的拦截日志保持一致。样例：
#   …voiceinput:   (疑似底噪幻觉，跳过): 语音0.05s 段长7.3s 2字 '我。' (需≥0.18s)
_LINE_NEW = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*?"
    r"疑似底噪幻觉，跳过\): 语音(?P<voiced>[\d.]+)s 段长(?P<seg>[\d.]+)s\s+"
    r"(?P<chars>\d+)字\s+'(?P<text>.*?)' \(需≥(?P<need>[\d.]+)s\)\s*$"
)
# 旧格式（按段长判定，已弃用）。样例：
#   …voiceinput:   (疑似底噪幻觉，跳过): 段长1.8s 2字 '嗯。' (上限1.5s)
_LINE_OLD = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*?"
    r"疑似底噪幻觉，跳过\): 段长(?P<seg>[\d.]+)s\s+(?P<chars>\d+)字\s+"
    r"'(?P<text>.*?)' \(上限(?P<limit>[\d.]+)s\)\s*$"
)


def _log_files() -> list[Path]:
    """当前日志 + 滚动备份(.3/.2/.1/base)，按从旧到新返回，使整体时间有序。"""
    d = log_dir()
    files: list[Path] = []
    for i in (3, 2, 1):          # 备份号越大越旧
        p = d / f"voiceinput.log.{i}"
        if p.exists():
            files.append(p)
    base = d / "voiceinput.log"
    if base.exists():
        files.append(base)
    return files


def _parse(line: str) -> dict | None:
    """把一行日志解析为拦截记录；非拦截行返回 None。"""
    m = _LINE_NEW.search(line)
    if m:
        return {
            "ts": m.group("ts"),
            "voiced": float(m.group("voiced")),   # 去静音后的语音时长（判定依据）
            "seg": float(m.group("seg")),          # 整段缓冲时长（含静音）
            "chars": int(m.group("chars")),
            "text": m.group("text"),
        }
    m = _LINE_OLD.search(line)
    if m:
        return {
            "ts": m.group("ts"),
            "voiced": None,                        # 旧格式无语音时长
            "seg": float(m.group("seg")),
            "chars": int(m.group("chars")),
            "text": m.group("text"),
        }
    return None


def load(limit: int = 1000) -> list[dict]:
    """扫描日志，返回拦截记录（最新在前，最多 limit 条）。无/不可读则空表。

    每条字段：ts(时间字符串)、voiced(语音时长秒，旧记录为 None)、seg(段长秒)、
    chars(字数)、text(被拦内容)。
    """
    recs: list[dict] = []
    for p in _log_files():       # 从旧到新：行天然按时间递增累积
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ln in text.splitlines():
            rec = _parse(ln)
            if rec is not None:
                recs.append(rec)
    recs.reverse()               # 旧→新读入 → 反转为最新在前
    return recs[:limit]
