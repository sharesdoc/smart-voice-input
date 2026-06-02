"""开机自启动 (FR-14)，基于 macOS LaunchAgent。

在 ~/Library/LaunchAgents/ 写入 plist，登录时以 `python -m voiceinput` 启动。
plist 内容生成为纯函数，便于单测；文件读写/launchctl 操作做异常保护。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_LABEL = "com.voiceinput.agent"


def plist_path() -> Path:
    override = os.environ.get("VOICEINPUT_LAUNCHAGENTS_DIR")
    base = Path(override) if override else Path.home() / "Library" / "LaunchAgents"
    return base / f"{_LABEL}.plist"


def build_plist(python_exe: str | None = None) -> str:
    """生成 LaunchAgent plist XML（纯函数）。"""
    py = python_exe or sys.executable
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key>\n  <string>{_LABEL}</string>\n"
        "  <key>ProgramArguments</key>\n"
        f"  <array>\n    <string>{py}</string>\n"
        "    <string>-m</string>\n    <string>voiceinput</string>\n  </array>\n"
        "  <key>RunAtLoad</key>\n  <true/>\n"
        "  <key>KeepAlive</key>\n  <false/>\n"
        "</dict>\n</plist>\n"
    )


def is_enabled() -> bool:
    return plist_path().exists()


def enable(python_exe: str | None = None) -> bool:
    """写入 plist 并尝试 load。返回是否成功。"""
    try:
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_plist(python_exe), encoding="utf-8")
        _launchctl("load", str(path))
        return True
    except Exception:
        return False


def disable() -> bool:
    """卸载并删除 plist。返回是否成功。"""
    try:
        path = plist_path()
        if path.exists():
            _launchctl("unload", str(path))
            path.unlink()
        return True
    except Exception:
        return False


def _launchctl(action: str, path: str) -> None:
    import subprocess

    try:
        subprocess.run(["launchctl", action, path], check=False,
                       capture_output=True)
    except Exception:
        pass  # launchctl 不可用不应阻断（plist 已写入，下次登录仍生效）
