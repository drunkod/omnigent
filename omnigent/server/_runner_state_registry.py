"""Last-known runner lifecycle state for fresh session-stream subscribers."""

from __future__ import annotations

import time

# ``runner_reconnected`` is a transient reconciliation edge, not a stable
# connectivity state. Keeping it forever means a browser whose SSE stream
# missed the following terminal-state burst replays an indefinite spinner on
# every reload. Bound only that transient replay; stable offline events remain
# sticky until a newer runner event replaces them.
_RECONNECT_REPLAY_TTL_SECONDS = 30.0
_last_runner_state: dict[str, tuple[dict[str, object], float]] = {}


def record(session_id: str, event: dict[str, object]) -> None:
    _last_runner_state[session_id] = (dict(event), time.monotonic())


def snapshot(session_id: str) -> dict[str, object] | None:
    entry = _last_runner_state.get(session_id)
    if entry is None:
        return None
    event, recorded_at = entry
    if (
        event.get("state") == "runner_reconnected"
        and time.monotonic() - recorded_at >= _RECONNECT_REPLAY_TTL_SECONDS
    ):
        # Reconciliation has a separate browser-side deadline. Expiring the
        # stale replay here prevents a late subscriber from re-entering the
        # transient state after that deadline has already elapsed.
        _last_runner_state.pop(session_id, None)
        return None
    return dict(event)


def clear(session_id: str) -> None:
    _last_runner_state.pop(session_id, None)


def reset_for_tests() -> None:
    _last_runner_state.clear()
