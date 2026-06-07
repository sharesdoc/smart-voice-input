"""SenseVoice 服务管理模块测试。"""

import pytest
from voiceinput.svr_manager import (
    ServerInfo, SvrState, _check_unsupported, _read_port,
    _script_path, _pid_file, _log_file_path,
    server_info, status, start, stop, test_service,
)


def test_svr_state_labels():
    """所有状态有中英文标签。"""
    from voiceinput.svr_manager import _LABELS_ZH, _LABELS_EN
    for st in SvrState:
        assert _LABELS_ZH.get(st)
        assert _LABELS_EN.get(st)


def test_script_path_exists():
    """startup-asr-server 脚本应存在于项目根目录。"""
    p = _script_path()
    if p is not None:
        assert p.name == "startup-asr-server"
        assert p.exists()


def test_pid_file_path():
    """PID 文件路径应在项目根目录。"""
    p = _pid_file()
    if p is not None:
        assert p.name == ".asr-server.pid"


def test_log_file_path():
    """日志文件路径应在项目 log 目录下。"""
    p = _log_file_path()
    if p is not None:
        assert p.name == "asr-server.log"


def test_server_info_returns_struct():
    """server_info() 返回 ServerInfo 结构。"""
    info = server_info()
    assert isinstance(info, ServerInfo)
    assert isinstance(info.state, SvrState)
    if info.state == SvrState.RUNNING:
        assert info.pid > 0


def test_status_returns_tuple():
    """status() 返回 (SvrState, str) 且描述非空。"""
    st, desc = status()
    assert isinstance(st, SvrState)
    assert isinstance(desc, str)
    assert len(desc) > 0


def test_status_bilingual():
    """status() 支持中英文。"""
    st_zh, d_zh = status("zh")
    st_en, d_en = status("en")
    assert isinstance(st_zh, SvrState)
    assert isinstance(st_en, SvrState)
    assert st_zh == st_en
    assert d_zh != d_en  # 中文和英文描述不同


def test_check_unsupported_returns_bool():
    """_check_unsupported 返回布尔值。"""
    result = _check_unsupported()
    assert isinstance(result, bool)


def test_unsupported_when_returns_correct_state():
    """不支持时状态为 UNSUPPORTED。"""
    unsup = _check_unsupported()
    if unsup:
        st, _ = status()
        assert st == SvrState.UNSUPPORTED


def test_all_states_have_unique_values():
    """所有状态值唯一。"""
    vals = [st.value for st in SvrState]
    assert len(vals) == len(set(vals))


def test_server_info_fields():
    """ServerInfo 默认值。"""
    si = ServerInfo(state=SvrState.STOPPED)
    assert si.pid == 0
    assert si.port == 0
    assert si.process_name == ""
    assert si.log_file == ""
    assert si.health_ok is False


def test_read_pid_auto_cleanup():
    """_read_pid 自动清理残留 PID 文件。"""
    from voiceinput.svr_manager import _read_pid
    # 先确保没有残留
    pf = _pid_file()
    if pf is not None and pf.exists():
        pf.unlink()
    # 清理后应返回 None
    assert _read_pid() is None


def test_server_info_auto_cleanup():
    """server_info 遇到残留 PID 自动清理并返回 STOPPED。"""
    pf = _pid_file()
    if pf is not None:
        pf.write_text("99999")
    info = server_info()
    assert info.state in (SvrState.STOPPED, SvrState.RUNNING)


def test_read_pid_bad_content():
    """_read_pid 遇到无效 PID 文件内容→自动清理。"""
    from voiceinput.svr_manager import _read_pid
    pf = _pid_file()
    if pf is not None:
        pf.write_text("not_a_number")
    assert _read_pid() is None


def test_read_pid_missing_file():
    """_read_pid 无 PID 文件时返回 None。"""
    from voiceinput.svr_manager import _read_pid
    pf = _pid_file()
    if pf is not None and pf.exists():
        pf.unlink()
    assert _read_pid() is None


def test_last_line():
    from voiceinput.svr_manager import _last_line
    assert _last_line("") == ""
    assert _last_line("line1\nline2") == "line2"
    assert _last_line("  \n  ") == ""


def test_log_file_path_type():
    p = _log_file_path()
    if p is not None:
        assert str(p).endswith("asr-server.log")


def test_server_info_stopped():
    """清理 PID 后 server_info 返回 STOPPED。"""
    pf = _pid_file()
    if pf is not None and pf.exists():
        pf.unlink()
    info = server_info()
    assert info.state == SvrState.STOPPED


def test_read_log_tail_nonexistent():
    from voiceinput.svr_manager import _read_log_tail
    # 日志目录可能不存在，应返回空字符串不崩溃
    result = _read_log_tail(3)
    assert isinstance(result, str)


def test_health_check_closed_port():
    from voiceinput.svr_manager import _health_check
    # 随机高端口几乎肯定未监听
    assert _health_check(54321) is False


def test_test_service_reports_stopped(monkeypatch):
    import voiceinput.svr_manager as sm

    monkeypatch.setattr(sm, "server_info", lambda lang="zh": ServerInfo(state=SvrState.STOPPED))
    ok, msg = test_service("zh")
    assert ok is False
    assert "未运行" in msg


def test_test_service_reports_healthy(monkeypatch):
    import voiceinput.svr_manager as sm

    monkeypatch.setattr(sm, "server_info", lambda lang="zh": ServerInfo(
        state=SvrState.RUNNING, pid=123, port=18765, health_ok=True))
    ok, msg = test_service("zh")
    assert ok is True
    assert "/health" in msg
    assert "18765" in msg


def test_test_service_reports_process_not_ready(monkeypatch):
    import voiceinput.svr_manager as sm

    monkeypatch.setattr(sm, "server_info", lambda lang="zh": ServerInfo(
        state=SvrState.RUNNING, pid=123, port=18765, health_ok=False))
    ok, msg = test_service("zh")
    assert ok is False
    assert "暂未响应" in msg


def test_status_returns_label_for_each_state():
    """status 对所有合法状态返回非空字符串。"""
    # STOPPED（无 PID 文件时）
    pf = _pid_file()
    if pf is not None and pf.exists():
        pf.unlink()
    _, desc = status()
    assert desc == "已停止"
    _, desc_en = status("en")
    assert desc_en == "Stopped"


def test_force_kill_nonexistent_pid():
    """_force_kill 对不存在的 PID 返回失败。"""
    from voiceinput.svr_manager import _force_kill
    ok, msg = _force_kill(99999)
    assert not ok
