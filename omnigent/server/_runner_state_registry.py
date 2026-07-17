"""Last-known runner lifecycle state for fresh session-stream subscribers."""

from __future__ import annotations

import asyncio
import time

# ``runner_reconnected`` is a transient reconciliation edge, not a stable
# connectivity state. Keeping it forever means a browser whose SSE stream
# missed the following terminal-state burst replays an indefinite spinner on
# every reload. Bound only that transient replay; stable offline events remain
# sticky until a newer runner event replaces them.
_RECONNECT_REPLAY_TTL_SECONDS = 30.0
# The app-level reconnect handler is bounded at 25 seconds. Give it one second
# of headroom, then emit a compatibility-safe terminal-state marker so existing
# clients leave ``runner_reconnected`` even when reconciliation returned an
# empty set, failed, timed out, or its terminal-state burst was missed.
_RECONNECT_SETTLE_SECONDS = 26.0
_RECONNECT_SENTINEL_TERMINAL_ID = "__runner_reconcile__"

_last_runner_state: dict[str, tuple[dict[str, object], float]] = {}
_reconnect_settle_handles: dict[str, asyncio.TimerHandle] = {}


def _cancel_settle_handle(session_id: str) -> None:
    handle = _reconnect_settle_handles.pop(session_id, None)
    if handle is not None:
        handle.cancel()


def _settle_if_still_reconnecting(
    session_id: str,
    runner_id: str,
    recorded_at: float,
) -> None:
    """Publish a bounded completion marker for an otherwise stuck reconnect."""
    _reconnect_settle_handles.pop(session_id, None)
    entry = _last_runner_state.get(session_id)
    if entry is None:
        return
    event, current_recorded_at = entry
    if (
        current_recorded_at != recorded_at
        or event.get("state") != "runner_reconnected"
        or event.get("runner_id") != runner_id
    ):
        return

    # Do not replay the transient edge to subscribers that arrive after the
    # deadline. The synthetic terminal event below releases currently mounted
    # clients through the existing reducer contract (any terminal-state frame
    # ends reconciliation) without widening the public SSE schema.
    _last_runner_state.pop(session_id, None)
    from omnigent.runtime import session_stream

    session_stream.publish(
        session_id,
        {
            "type": "session.terminal_state",
            "conversation_id": session_id,
            "terminal_id": _RECONNECT_SENTINEL_TERMINAL_ID,
            "state": "terminal_unknown",
        },
    )


def record(session_id: str, event: dict[str, object]) -> None:
    _cancel_settle_handle(session_id)
    recorded_at = time.monotonic()
    copied_event = dict(event)
    _last_runner_state[session_id] = (copied_event, recorded_at)

    if copied_event.get("state") != "runner_reconnected":
        return
    runner_id = copied_event.get("runner_id")
    if not isinstance(runner_id, str) or not runner_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Synchronous unit tests and import-time callers have no running loop.
        # Replay TTL still bounds the transient state; production record calls
        # happen on the server event loop and schedule the live fallback.
        return
    _reconnect_settle_handles[session_id] = loop.call_later(
        _RECONNECT_SETTLE_SECONDS,
        _settle_if_still_reconnecting,
        session_id,
        runner_id,
        recorded_at,
    )


def snapshot(session_id: str) -> dict[str, object] | None:
    entry = _last_runner_state.get(session_id)
    if entry is None:
        return None
    event, recorded_at = entry
    if (
        event.get("state") == "runner_reconnected"
        and time.monotonic() - recorded_at >= _RECONNECT_REPLAY_TTL_SECONDS
    ):
        # Expiring the stale replay prevents a late subscriber from re-entering
        # the transient state after both server and browser deadlines elapsed.
        _cancel_settle_handle(session_id)
        _last_runner_state.pop(session_id, None)
        return None
    return dict(event)


def clear(session_id: str) -> None:
    _cancel_settle_handle(session_id)
    _last_runner_state.pop(session_id, None)


def reset_for_tests() -> None:
    for handle in _reconnect_settle_handles.values():
        handle.cancel()
    _reconnect_settle_handles.clear()
    _last_runner_state.clear()
