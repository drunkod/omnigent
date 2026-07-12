from __future__ import annotations

import httpx
import pytest

from omnigent.errors import OmnigentError
from omnigent.server._elicitation_registry import _local_action_elicitations
from omnigent.server.auth import LEVEL_OWNER
from omnigent.server.routes.sessions import _resolve_elicitation


class _Grant:
    def __init__(self, user_id: str, level: int) -> None:
        self.user_id = user_id
        self.level = level


class _PermissionStore:
    def __init__(self, owner: str | None) -> None:
        self.owner = owner

    def list_for_session(self, _session_id: str) -> list[_Grant]:
        return [_Grant(self.owner, LEVEL_OWNER)]


@pytest.mark.asyncio
async def test_local_action_owner_approval_resolves_and_is_removed() -> None:
    elicitation_id = "elicit_local_owner"
    _local_action_elicitations[elicitation_id] = "conv_test"
    await _resolve_elicitation(
        "conv_test",
        {"elicitation_id": elicitation_id, "action": "accept"},
        None,
        user_id="alice",
        permission_store=_PermissionStore("alice"),
    )
    assert elicitation_id not in _local_action_elicitations


@pytest.mark.asyncio
async def test_local_action_collaborator_is_denied_and_id_remains_parked() -> None:
    elicitation_id = "elicit_local_collaborator"
    _local_action_elicitations[elicitation_id] = "conv_test"
    with pytest.raises(OmnigentError, match="only the session owner"):
        await _resolve_elicitation(
            "conv_test",
            {"elicitation_id": elicitation_id, "action": "accept"},
            None,
            user_id="bob",
            permission_store=_PermissionStore("alice"),
        )
    assert elicitation_id in _local_action_elicitations
    _local_action_elicitations.pop(elicitation_id, None)


@pytest.mark.asyncio
async def test_wrong_session_cannot_consume_local_action_tag() -> None:
    elicitation_id = "elicit_cross_session"
    _local_action_elicitations[elicitation_id] = "conv_a"

    await _resolve_elicitation(
        "conv_b",
        {"elicitation_id": elicitation_id, "action": "accept"},
        None,
        user_id="bob",
        permission_store=_PermissionStore("bob"),
    )
    assert _local_action_elicitations[elicitation_id] == "conv_a"

    with pytest.raises(OmnigentError, match="only the session owner"):
        await _resolve_elicitation(
            "conv_a",
            {"elicitation_id": elicitation_id, "action": "accept"},
            None,
            user_id="bob",
            permission_store=_PermissionStore("alice"),
        )
    _local_action_elicitations.pop(elicitation_id, None)


@pytest.mark.asyncio
async def test_auth_disabled_ownerless_session_can_approve() -> None:
    elicitation_id = "elicit_auth_off"
    _local_action_elicitations[elicitation_id] = "conv_local"
    await _resolve_elicitation(
        "conv_local",
        {"elicitation_id": elicitation_id, "action": "accept"},
        None,
        user_id=None,
        permission_store=_PermissionStore(None),
    )
    assert elicitation_id not in _local_action_elicitations


@pytest.mark.asyncio
async def test_local_action_denial_forwards_decline_to_runner(monkeypatch) -> None:
    elicitation_id = "elicit_local_denied"
    forwarded: list[dict[str, object]] = []
    _local_action_elicitations[elicitation_id] = "conv_test"

    async def capture_forward(_session_id, data, _runner_router) -> None:
        forwarded.append(data)

    monkeypatch.setattr(
        "omnigent.server.routes.sessions._forward_approval_to_runner",
        capture_forward,
    )
    try:
        await _resolve_elicitation(
            "conv_test",
            {"elicitation_id": elicitation_id, "action": "decline"},
            None,
            user_id="alice",
            permission_store=_PermissionStore("alice"),
        )
    finally:
        _local_action_elicitations.pop(elicitation_id, None)

    assert forwarded == [{"elicitation_id": elicitation_id, "action": "decline"}]


@pytest.mark.asyncio
async def test_runner_disconnect_consumes_resolution_and_requires_fresh_action(
    monkeypatch,
) -> None:
    """A failed forward clears the stale prompt instead of replaying execution."""
    elicitation_id = "elicit_runner_disconnected"
    _local_action_elicitations[elicitation_id] = "conv_test"

    class _DisconnectedClient:
        async def post(self, *_args, **_kwargs) -> None:
            raise httpx.ConnectError("runner disconnected")

    async def disconnected_client(*_args, **_kwargs) -> _DisconnectedClient:
        return _DisconnectedClient()

    monkeypatch.setattr(
        "omnigent.server.routes.sessions._get_runner_client",
        disconnected_client,
    )

    await _resolve_elicitation(
        "conv_test",
        {"elicitation_id": elicitation_id, "action": "accept"},
        object(),  # type: ignore[arg-type]
        user_id="alice",
        permission_store=_PermissionStore("alice"),
    )

    assert elicitation_id not in _local_action_elicitations
