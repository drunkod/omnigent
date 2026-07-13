"""Last-known runner lifecycle state for fresh session-stream subscribers."""

from __future__ import annotations

_last_runner_state: dict[str, dict[str, object]] = {}


def record(session_id: str, event: dict[str, object]) -> None:
    _last_runner_state[session_id] = dict(event)


def snapshot(session_id: str) -> dict[str, object] | None:
    event = _last_runner_state.get(session_id)
    return dict(event) if event is not None else None


def clear(session_id: str) -> None:
    _last_runner_state.pop(session_id, None)


def reset_for_tests() -> None:
    _last_runner_state.clear()
