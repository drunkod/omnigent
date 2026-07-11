from __future__ import annotations

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
    def __init__(self, owner: str) -> None:
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
