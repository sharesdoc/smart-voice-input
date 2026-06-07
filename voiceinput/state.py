"""应用状态机 (FR-01, 需求文档 §7)。

状态流转：
    Idle ─双击⌘─▶ Listening ─结束录音─▶ Transcribing ─原始文本─▶ Injecting
      ▲                                                              │
      │                                            (organize/polish)  ▼
      │                                                          Refining
      │                                                              │
      │                          整理结果≠已注入 ──是──▶ Rewriting
      └──────────────── 完成 ◀──────────────────────────┴── 否(保持) ─┘
    任意态遇异常/被用户打断 ──▶ Error ──放弃重写、保留原文──▶ Idle
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional


class AppState(Enum):
    """菜单栏可见的运行状态。值为给用户展示的中文标签。"""

    IDLE = "空闲"
    LISTENING = "聆听中"
    TRANSCRIBING = "识别中"
    REFINING = "整理中"
    REWRITING = "重写中"
    INJECTING = "注入中"
    ERROR = "错误"

    @property
    def icon(self) -> str:
        """状态对应的菜单栏图标字符（占位，正式版用模板图标）。"""
        return {
            AppState.IDLE: "🐰",
            AppState.LISTENING: "🎙️",
            AppState.TRANSCRIBING: "✍️",
            AppState.REFINING: "🧠",
            AppState.REWRITING: "♻️",
            AppState.INJECTING: "⌨️",
            AppState.ERROR: "⚠️",
        }[self]


# 合法的状态迁移表：from -> {允许到达的状态集合}
_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.IDLE: {AppState.LISTENING, AppState.ERROR},
    AppState.LISTENING: {AppState.TRANSCRIBING, AppState.IDLE, AppState.ERROR},
    AppState.TRANSCRIBING: {
        AppState.INJECTING,
        AppState.REFINING,
        AppState.IDLE,
        AppState.ERROR,
    },
    AppState.INJECTING: {
        AppState.REFINING,
        AppState.IDLE,
        AppState.ERROR,
    },
    AppState.REFINING: {AppState.REWRITING, AppState.IDLE, AppState.ERROR},
    AppState.REWRITING: {AppState.IDLE, AppState.ERROR},
    AppState.ERROR: {AppState.IDLE},
}


class IllegalTransition(RuntimeError):
    """非法状态迁移。"""


class StateMachine:
    """轻量状态机，校验迁移合法性并回调通知（用于刷新菜单栏图标）。"""

    def __init__(
        self,
        on_change: Optional[Callable[[AppState, AppState], None]] = None,
    ) -> None:
        self._state = AppState.IDLE
        self._on_change = on_change

    @property
    def state(self) -> AppState:
        return self._state

    def can_transition(self, to: AppState) -> bool:
        return to in _TRANSITIONS.get(self._state, set())

    def transition(self, to: AppState) -> None:
        """执行状态迁移；非法迁移抛 IllegalTransition。"""
        if to == self._state:
            return
        if not self.can_transition(to):
            raise IllegalTransition(f"{self._state.name} -> {to.name} 非法")
        old = self._state
        self._state = to
        if self._on_change is not None:
            self._on_change(old, to)

    def force_idle(self) -> None:
        """异常恢复：从任意状态强制回到空闲（不校验）。"""
        self.set_state(AppState.IDLE)

    def set_state(self, to: AppState) -> None:
        """宽松设置状态（不校验迁移）。

        用于连续听写等非线性场景：一段处理完需从 INJECTING 直接回到 LISTENING，
        这类流转不在严格迁移表内。
        """
        old = self._state
        if old == to:
            return
        self._state = to
        if self._on_change is not None:
            self._on_change(old, to)
