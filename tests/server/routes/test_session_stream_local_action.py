from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from omnigent.server.routes import sessions


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_local_action_audit_does_not_hide_following_elicitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit edge and following approval both cross one live SSE stream."""

    async def _subscribe(*_args: object, **_kwargs: object) -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "session.local_action",
            "action_id": "act_123",
            "session_id": "conv_abc",
            "runner_id": "runner_local",
            "workspace_id": "ws_123",
            "kind": "write_file",
            "requested_by": "agent",
            "policy_mode": "manual",
            "status": "requested",
        }
        yield {
            "type": "response.elicitation_request",
            "elicitation_id": "elicit_123",
            "params": {
                "message": "Approve local action: write_file",
                "local_action": {
                    "version": 1,
                    "action_id": "act_123",
                    "kind": "write_file",
                    "policy_mode": "manual",
                    "cwd": ".",
                    "path_summary": ["demo.txt"],
                    "risk_flags": ["writes_files"],
                },
            },
        }

    monkeypatch.setattr(sessions.session_stream, "subscribe", _subscribe)
    stream = sessions._stream_live_events(_ConnectedRequest(), "conv_abc")  # type: ignore[arg-type]

    audit_frame = await anext(stream)
    approval_frame = await anext(stream)
    done_frame = await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    assert "event: session.local_action" in audit_frame
    assert json.loads(audit_frame.split("data: ", 1)[1])["action_id"] == "act_123"
    assert "event: response.elicitation_request" in approval_frame
    assert json.loads(approval_frame.split("data: ", 1)[1])["elicitation_id"] == "elicit_123"
    assert done_frame == "data: [DONE]\n\n"
