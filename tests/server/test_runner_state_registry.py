from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from omnigent.runtime import session_stream
from omnigent.server import _runner_state_registry


def setup_function() -> None:
    _runner_state_registry.reset_for_tests()


def teardown_function() -> None:
    _runner_state_registry.reset_for_tests()


def test_stable_runner_state_remains_replayable() -> None:
    event = {
        "type": "session.runner_state",
        "conversation_id": "conv_1",
        "runner_id": "runner_1",
        "state": "runner_offline",
    }
    with patch.object(_runner_state_registry.time, "monotonic", return_value=10.0):
        _runner_state_registry.record("conv_1", event)
    with patch.object(_runner_state_registry.time, "monotonic", return_value=1000.0):
        assert _runner_state_registry.snapshot("conv_1") == event


def test_transient_reconnected_state_expires_from_replay() -> None:
    event = {
        "type": "session.runner_state",
        "conversation_id": "conv_1",
        "runner_id": "runner_1",
        "state": "runner_reconnected",
    }
    with patch.object(_runner_state_registry.time, "monotonic", return_value=10.0):
        _runner_state_registry.record("conv_1", event)
    with patch.object(
        _runner_state_registry.time,
        "monotonic",
        return_value=10.0 + _runner_state_registry._RECONNECT_REPLAY_TTL_SECONDS,
    ):
        assert _runner_state_registry.snapshot("conv_1") is None
        assert _runner_state_registry.snapshot("conv_1") is None


def test_recent_reconnected_state_is_still_replayable() -> None:
    event = {
        "type": "session.runner_state",
        "conversation_id": "conv_1",
        "runner_id": "runner_1",
        "state": "runner_reconnected",
    }
    with patch.object(_runner_state_registry.time, "monotonic", return_value=10.0):
        _runner_state_registry.record("conv_1", event)
    with patch.object(_runner_state_registry.time, "monotonic", return_value=20.0):
        assert _runner_state_registry.snapshot("conv_1") == event


@pytest.mark.asyncio
async def test_reconnect_deadline_publishes_completion_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(_runner_state_registry, "_RECONNECT_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(
        session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)),
    )

    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_reconnected",
        },
    )
    await asyncio.sleep(0.001)

    assert _runner_state_registry.snapshot("conv_1") is None
    assert published == [
        (
            "conv_1",
            {
                "type": "session.terminal_state",
                "conversation_id": "conv_1",
                "terminal_id": "__runner_reconcile__",
                "state": "terminal_unknown",
            },
        )
    ]


@pytest.mark.asyncio
async def test_successful_reconciliation_cancels_deadline_without_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)),
    )

    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_reconnected",
        },
    )
    _runner_state_registry.complete_reconciliation("conv_1", "runner_1", terminal_count=1)

    assert _runner_state_registry.snapshot("conv_1") is None
    assert published == []
    assert "conv_1" not in _runner_state_registry._reconnect_settle_handles


def test_empty_reconciliation_publishes_completion_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)),
    )

    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_reconnected",
        },
    )
    _runner_state_registry.complete_reconciliation("conv_1", "runner_1", terminal_count=0)

    assert _runner_state_registry.snapshot("conv_1") is None
    assert published == [
        (
            "conv_1",
            {
                "type": "session.terminal_state",
                "conversation_id": "conv_1",
                "terminal_id": "__runner_reconcile__",
                "state": "terminal_unknown",
            },
        )
    ]


def test_reconciliation_completion_preserves_newer_runner_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)),
    )
    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_reconnected",
        },
    )
    offline = {
        "type": "session.runner_state",
        "conversation_id": "conv_1",
        "runner_id": "runner_1",
        "state": "runner_offline",
    }
    _runner_state_registry.record("conv_1", offline)

    _runner_state_registry.complete_reconciliation("conv_1", "runner_1", terminal_count=0)

    assert _runner_state_registry.snapshot("conv_1") == offline
    assert published == []


@pytest.mark.asyncio
async def test_newer_runner_state_cancels_reconnect_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(_runner_state_registry, "_RECONNECT_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(
        session_stream,
        "publish",
        lambda session_id, event: published.append((session_id, event)),
    )

    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_reconnected",
        },
    )
    _runner_state_registry.record(
        "conv_1",
        {
            "type": "session.runner_state",
            "conversation_id": "conv_1",
            "runner_id": "runner_1",
            "state": "runner_offline",
        },
    )
    await asyncio.sleep(0)

    assert published == []
    assert _runner_state_registry.snapshot("conv_1") == {
        "type": "session.runner_state",
        "conversation_id": "conv_1",
        "runner_id": "runner_1",
        "state": "runner_offline",
    }
