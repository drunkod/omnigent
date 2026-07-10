"""Shared terminal and runner states emitted by remote session lifecycles."""

from enum import Enum


class TerminalUiState(str, Enum):
    """States the web and desktop clients can render for a remote session."""

    TERMINAL_UNKNOWN = "terminal_unknown"
    TERMINAL_STARTING = "terminal_starting"
    TERMINAL_RUNNING = "terminal_running"
    TERMINAL_DETACHED = "terminal_detached"
    TERMINAL_EXITED = "terminal_exited"
    RUNNER_OFFLINE = "runner_offline"
    RUNNER_RECONNECTED = "runner_reconnected"
    TERMINAL_RELAUNCHING = "terminal_relaunching"
    TERMINAL_FAILED = "terminal_failed"
