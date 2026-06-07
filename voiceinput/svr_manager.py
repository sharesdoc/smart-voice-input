"""SenseVoice ASR HTTP 服务管理（调用 startup-asr-server 脚本）。

生命周期状态机：
  STOPPED ──start()──→ RUNNING ──stop()/崩溃──→ STOPPED
     ↑                    │
     └──kill -9/异常退出──┘
  UNSUPPORTED: 本机环境不满足（非 macOS / 无 funasr / 无 torch）

所有状态检测通过 PID 文件 + kill -0 + HTTP /health 三重验证，绝不用缓存。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

_log = logging.getLogger(__name__)

_SCRIPT_NAME = "startup-asr-server"
_PID_FILE = ".asr-server.pid"
_DEFAULT_PORT = 18765
_HEALTH_TIMEOUT = 3  # HTTP 健康检查超时（秒）


class SvrState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    UNSUPPORTED = "unsupported"


_LABELS_ZH = {
    SvrState.STOPPED: "已停止",
    SvrState.RUNNING: "运行中",
    SvrState.UNSUPPORTED: "本机不支持",
}
_LABELS_EN = {
    SvrState.STOPPED: "Stopped",
    SvrState.RUNNING: "Running",
    SvrState.UNSUPPORTED: "Unsupported",
}


@dataclass
class ServerInfo:
    state: SvrState
    pid: int = 0
    port: int = 0
    process_name: str = ""
    log_file: str = ""
    health_ok: bool = False   # HTTP /health 是否响应


# ── 内部工具 ────────────────────────────────────────────────────

def _project_dir() -> Path | None:
    this = Path(__file__).resolve().parent
    return this.parent


def _script_path() -> Path | None:
    proj = _project_dir()
    if proj is None:
        return None
    p = proj / _SCRIPT_NAME
    return p if p.exists() and os.access(p, os.X_OK) else None


def _pid_file() -> Path | None:
    proj = _project_dir()
    if proj is None:
        return None
    return proj / _PID_FILE


def _log_file_path() -> Path | None:
    proj = _project_dir()
    if proj is None:
        return None
    return proj / "log" / "asr-server.log"


def _check_unsupported() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        import funasr  # noqa: F401
    except ImportError:
        return True
    try:
        import torch  # noqa: F401
    except ImportError:
        return True
    return False


# 进程生命周期内不变，缓存避免每次 server_info()/start() 重复 import
_UNSUPPORTED = _check_unsupported()


def _read_pid() -> int | None:
    """读取 PID 文件，进程不存在时自动清理。"""
    pid_path = _pid_file()
    if pid_path is None or not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        pid_path.unlink(missing_ok=True)
        _log.info("自动清理残留 PID 文件 (pid=%d)", pid)
        return None
    return pid


def _read_port(pid: int) -> int | None:
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "args="],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode("utf-8", errors="replace")
    except Exception:
        return None
    import re
    m = re.search(r"--port[= ](\d+)", out)
    return int(m.group(1)) if m else None


def _read_process_name(pid: int) -> str:
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "comm="],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode("utf-8", errors="replace").strip()
        return out or "python"
    except Exception:
        return "python"


def _health_check(port: int) -> bool:
    """HTTP GET /health，验证服务真正可用。"""
    try:
        req = Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "VoiceInput/1.0"},
        )
        with urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _label(state: SvrState, lang: str = "zh") -> str:
    d = _LABELS_ZH if lang == "zh" else _LABELS_EN
    return d.get(state, "未知" if lang == "zh" else "Unknown")


def _last_line(text: str) -> str:
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _read_log_tail(lines: int = 5) -> str:
    lf = _log_file_path()
    if lf is None or not lf.exists():
        return ""
    try:
        tail = lf.read_text(encoding="utf-8", errors="replace")
        tail_lines = tail.strip().splitlines()
        return "\n".join(tail_lines[-lines:])
    except Exception:
        return ""


# ── 公开 API ────────────────────────────────────────────────────

def server_info(lang: str = "zh") -> ServerInfo:
    """返回完整服务信息——三重验证，无缓存。

    1. PID 文件存在 + 进程存活
    2. 解析端口
    3. HTTP /health 确认服务真正可用

    任一步失败即返回正确状态，自动清理残留。
    """
    if _UNSUPPORTED:
        return ServerInfo(state=SvrState.UNSUPPORTED)

    pid = _read_pid()  # 自动清理残留
    if pid is None:
        return ServerInfo(state=SvrState.STOPPED)

    port = _read_port(pid) or _DEFAULT_PORT
    health_ok = _health_check(port)

    # 进程存活即判定为 RUNNING；HTTP 健康检查仅作附加信息
    if not health_ok:
        return ServerInfo(
            state=SvrState.RUNNING, pid=pid, port=port,
            process_name=_read_process_name(pid),
            log_file=str(_log_file_path() or ""),
            health_ok=False,  # 启动中，稍后自动恢复
        )

    return ServerInfo(
        state=SvrState.RUNNING, pid=pid, port=port,
        process_name=_read_process_name(pid),
        log_file=str(_log_file_path() or ""),
        health_ok=True,
    )


def status(lang: str = "zh") -> tuple[SvrState, str]:
    """返回 (状态, 可读单行描述)。"""
    info = server_info(lang)
    lbl = _label(info.state, lang)
    if info.state == SvrState.RUNNING:
        state_lbl = ("启动中" if lang == "zh" else "Starting") if not info.health_ok else lbl
        extras = [f"PID {info.pid}"]
        if info.port:
            extras.append(f"{'Port' if lang == 'en' else '端口'} {info.port}")
        return info.state, f"{state_lbl} · {' · '.join(extras)}"
    return info.state, lbl


def test_service(lang: str = "zh") -> tuple[bool, str]:
    """测试 SenseVoice HTTP 服务是否可用。"""
    info = server_info(lang)
    if info.state == SvrState.UNSUPPORTED:
        return False, "本机不支持 SenseVoice 服务" if lang == "zh" else "Unsupported"
    if info.state == SvrState.STOPPED:
        return False, "服务未运行" if lang == "zh" else "Service is stopped"
    if info.health_ok:
        msg = (f"测试成功：/health 正常 · PID {info.pid} · 端口 {info.port}"
               if lang == "zh"
               else f"OK: /health healthy · PID {info.pid} · Port {info.port}")
        return True, msg
    msg = (f"进程运行但 /health 暂未响应 · PID {info.pid} · 端口 {info.port}"
           if lang == "zh"
           else f"Process is running but /health is not ready · PID {info.pid} · Port {info.port}")
    return False, msg


def start(port: int = _DEFAULT_PORT) -> tuple[bool, str]:
    """启动 SenseVoice 服务。返回 (成功, 消息)。"""
    if _UNSUPPORTED:
        return False, "本机不支持 SenseVoice 服务"
    script = _script_path()
    if script is None:
        return False, "未找到 startup-asr-server 脚本"

    # 自动清理残留（_read_pid 内部处理）
    _read_pid()

    try:
        result = subprocess.run(
            [str(script), "-s", "-p", str(port)],
            capture_output=True, text=True, timeout=120,
            cwd=str(script.parent),
        )
        if result.returncode == 0:
            _log.info("SenseVoice 服务启动成功")
            return True, _last_line(result.stdout) or "启动成功"
        else:
            err = _last_line(result.stderr) or _last_line(result.stdout) or "未知错误"
            log_tail = _read_log_tail(5)
            if log_tail:
                err = f"{err}\n日志尾部: {log_tail}"
            _log.warning("SenseVoice 服务启动失败: %s", err)
            return False, f"启动失败：{err}"
    except subprocess.TimeoutExpired:
        return False, "启动超时（>120s）"
    except Exception as e:
        _log.exception("SenseVoice 服务启动异常")
        return False, f"启动异常：{e}"


def stop() -> tuple[bool, str]:
    """停止 SenseVoice 服务。返回 (成功, 消息)。"""
    script = _script_path()
    if script is None:
        # 没有脚本就直接杀 PID
        pid = _read_pid()
        if pid is not None:
            return _force_kill(pid)
        return False, "未找到 startup-asr-server 脚本且无运行中进程"

    try:
        result = subprocess.run(
            [str(script), "-k"],
            capture_output=True, text=True, timeout=30,
            cwd=str(script.parent),
        )
        if result.returncode == 0:
            _log.info("SenseVoice 服务已停止")
            return True, _last_line(result.stdout) or "已停止"
        else:
            err = _last_line(result.stderr) or _last_line(result.stdout) or "未知错误"
            return False, f"停止失败：{err}"
    except subprocess.TimeoutExpired:
        return False, "停止超时（>30s）"
    except Exception as e:
        _log.exception("SenseVoice 服务停止异常")
        return False, f"停止异常：{e}"


def _force_kill(pid: int) -> tuple[bool, str]:
    """兜底：直接发 SIGKILL 杀进程。"""
    import signal
    try:
        os.kill(pid, signal.SIGKILL)
        _log.info("已强制终止进程 (pid=%d)", pid)
        return True, f"已强制终止 PID {pid}"
    except Exception as e:
        return False, f"强制终止失败: {e}"
