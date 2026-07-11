"""Tests for T04 local-runner session-binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.session_binding import (
    EXECUTION_MODE_LABEL_KEY,
    LOCAL_RUNNER_EXECUTION_MODE,
    LOCAL_RUNNER_POLICY_LABEL_KEY,
    WORKSPACE_ID_LABEL_KEY,
    WORKSPACE_LABEL_LABEL_KEY,
    advertised_workspace_ids,
    advertised_workspace_label,
    merge_local_runner_labels,
    runner_notification_binding_payload,
    validate_local_runner_binding,
    validate_workspace_requires_runner,
)


@dataclass
class _Hello:
    harnesses: list[str]
    workspace_roots: list[dict[str, Any]]


@dataclass
class _Session:
    hello: _Hello
    owner: str | None = None


class _Registry:
    def __init__(self, sessions: dict[str, _Session] | None = None) -> None:
        self._sessions = sessions or {}

    def get(self, runner_id: str) -> _Session | None:
        return self._sessions.get(runner_id)


_WORKSPACE = {
    "workspace_id": "ws_abc123",
    "display_name": "demo",
    "path_label": "~/projects/demo",
    "capabilities": ["read", "write", "shell", "git", "terminal"],
}


def _registry(*, owner: str | None = None, harnesses: list[str] | None = None) -> _Registry:
    return _Registry(
        {
            "runner_test1": _Session(
                owner=owner,
                hello=_Hello(
                    harnesses=harnesses or ["codex"],
                    workspace_roots=[dict(_WORKSPACE)],
                ),
            )
        }
    )


def test_workspace_requires_runner() -> None:
    with pytest.raises(ValueError, match="workspace_id requires runner_id"):
        validate_workspace_requires_runner(runner_id=None, workspace_id="ws_abc123")


def test_validate_local_runner_binding_accepts_online_owner_harness_and_workspace() -> None:
    session = validate_local_runner_binding(
        runner_id="runner_test1",
        workspace_id="ws_abc123",
        registry=_registry(owner="alice@example.com"),
        user_id="alice@example.com",
        harness="codex",
    )

    assert session is not None
    assert session.hello.workspace_roots[0]["workspace_id"] == "ws_abc123"


def test_validate_local_runner_binding_allows_legacy_unowned_runner() -> None:
    assert (
        validate_local_runner_binding(
            runner_id="runner_test1",
            workspace_id="ws_abc123",
            registry=_registry(owner=None),
            user_id="alice@example.com",
            harness="codex",
        )
        is not None
    )


def test_validate_local_runner_binding_rejects_offline_runner() -> None:
    with pytest.raises(OmnigentError) as excinfo:
        validate_local_runner_binding(
            runner_id="runner_gone",
            workspace_id="ws_abc123",
            registry=_Registry(),
            user_id="alice@example.com",
            harness="codex",
        )

    assert excinfo.value.code == ErrorCode.RUNNER_UNAVAILABLE


def test_validate_local_runner_binding_rejects_foreign_runner() -> None:
    with pytest.raises(OmnigentError) as excinfo:
        validate_local_runner_binding(
            runner_id="runner_test1",
            workspace_id="ws_abc123",
            registry=_registry(owner="alice@example.com"),
            user_id="bob@example.com",
            harness="codex",
        )

    assert excinfo.value.code == ErrorCode.FORBIDDEN


def test_validate_local_runner_binding_rejects_harness_mismatch() -> None:
    with pytest.raises(OmnigentError) as excinfo:
        validate_local_runner_binding(
            runner_id="runner_test1",
            workspace_id="ws_abc123",
            registry=_registry(harnesses=["claude-native"]),
            user_id="alice@example.com",
            harness="codex",
        )

    assert excinfo.value.code == ErrorCode.RUNNER_CAPABILITY_MISMATCH


def test_validate_local_runner_binding_rejects_unknown_workspace() -> None:
    with pytest.raises(OmnigentError) as excinfo:
        validate_local_runner_binding(
            runner_id="runner_test1",
            workspace_id="ws_other",
            registry=_registry(),
            user_id=None,
            harness="codex",
        )

    assert excinfo.value.code == ErrorCode.WORKSPACE_NOT_FOUND


def test_advertised_workspace_helpers_ignore_malformed_entries() -> None:
    hello = _Hello(
        harnesses=[],
        workspace_roots=[
            dict(_WORKSPACE),
            {"workspace_id": ""},
            {"workspace_id": 4},
            "not-a-dict",  # type: ignore[list-item]
        ],
    )

    assert advertised_workspace_ids(hello) == {"ws_abc123"}
    assert advertised_workspace_label(hello, "ws_abc123") == "~/projects/demo"
    assert advertised_workspace_label(hello, "ws_other") is None


def test_advertised_workspace_label_falls_back_to_display_name() -> None:
    hello = _Hello(
        harnesses=[],
        workspace_roots=[{"workspace_id": "ws_abc123", "display_name": "demo"}],
    )

    assert advertised_workspace_label(hello, "ws_abc123") == "demo"


def test_merge_local_runner_labels_adds_binding_without_overwriting_paths() -> None:
    merged = merge_local_runner_labels(
        {"team": "ml"},
        runner_id="runner_test1",
        workspace_id="ws_abc123",
        workspace_label="~/projects/demo",
    )

    assert merged == {
        "team": "ml",
        EXECUTION_MODE_LABEL_KEY: LOCAL_RUNNER_EXECUTION_MODE,
        WORKSPACE_ID_LABEL_KEY: "ws_abc123",
        WORKSPACE_LABEL_LABEL_KEY: "~/projects/demo",
    }
    assert "workspace" not in merged


def test_merge_local_runner_labels_noops_without_runner() -> None:
    assert merge_local_runner_labels(
        {"team": "ml"},
        runner_id=None,
        workspace_id="ws_abc123",
        workspace_label="~/projects/demo",
    ) == {"team": "ml"}


def test_runner_notification_binding_payload_reads_contract_labels() -> None:
    payload = runner_notification_binding_payload(
        {
            EXECUTION_MODE_LABEL_KEY: LOCAL_RUNNER_EXECUTION_MODE,
            WORKSPACE_ID_LABEL_KEY: "ws_abc123",
        }
    )

    assert payload == {
        "workspace_id": "ws_abc123",
        "execution_mode": LOCAL_RUNNER_EXECUTION_MODE,
    }


def test_runner_notification_binding_payload_omits_missing_labels() -> None:
    assert runner_notification_binding_payload({}) == {}


def test_runner_tool_dispatch_binding_constants_match_server_contract() -> None:
    from omnigent.runner import tool_dispatch

    assert tool_dispatch._LOCAL_RUNNER_EXECUTION_MODE == LOCAL_RUNNER_EXECUTION_MODE
    assert tool_dispatch._EXECUTION_MODE_LABEL_KEY == EXECUTION_MODE_LABEL_KEY
    assert tool_dispatch._WORKSPACE_ID_LABEL_KEY == WORKSPACE_ID_LABEL_KEY
    assert tool_dispatch._LOCAL_RUNNER_POLICY_LABEL_KEY == LOCAL_RUNNER_POLICY_LABEL_KEY
