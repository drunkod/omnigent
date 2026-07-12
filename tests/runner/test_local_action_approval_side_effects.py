import asyncio
from typing import Any

import httpx
import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.policies.types import PolicyMode
from omnigent.runner import create_runner_app, pending_approvals
from omnigent.runner.local_actions import LocalActionGateway
from omnigent.runner.workspace_registry import WorkspaceRegistry


def _gateway(tmp_path, approve, audits):
    registry = WorkspaceRegistry()
    workspace = registry.add_path(tmp_path)
    gateway = LocalActionGateway(
        workspaces=registry,
        runner_id="runner_test",
        publish_audit=lambda record: audits.append(record.to_event()),
        request_approval=approve,
    )
    return gateway, workspace.workspace_id


@pytest.mark.asyncio
async def test_owner_approval_writes_reviewed_content_once(tmp_path) -> None:
    captured = []
    audits = []

    async def approve(record, **payload):
        captured.append(payload)
        return True

    gateway, workspace_id = _gateway(tmp_path, approve, audits)
    target = tmp_path / "note.txt"
    target.write_text("before\n", encoding="utf-8")
    result = await gateway.write_file(
        session_id="conv_owner",
        workspace_id=workspace_id,
        path="note.txt",
        content="after\n",
        mode=PolicyMode.MANUAL,
    )

    assert target.read_text(encoding="utf-8") == "after\n"
    assert result["bytes_written"] == len(b"after\n")
    assert captured[0]["diff_preview"].startswith("--- a/note.txt")
    assert captured[0]["diff_truncated"] is False
    assert [event["status"] for event in audits] == ["requested", "approved", "completed"]


@pytest.mark.asyncio
async def test_denied_write_leaves_file_unchanged(tmp_path) -> None:
    audits = []

    async def deny(record, **payload):
        return False

    gateway, workspace_id = _gateway(tmp_path, deny, audits)
    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(OmnigentError) as exc_info:
        await gateway.write_file(
            session_id="conv_owner",
            workspace_id=workspace_id,
            path="note.txt",
            content="replacement",
            mode=PolicyMode.MANUAL,
        )
    assert exc_info.value.code == ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL
    assert target.read_text(encoding="utf-8") == "original"
    assert [event["status"] for event in audits] == ["requested", "denied"]


@pytest.mark.asyncio
async def test_changed_target_conflicts_without_stale_write(tmp_path) -> None:
    audits = []
    target = tmp_path / "note.txt"
    target.write_text("reviewed", encoding="utf-8")

    async def mutate_then_approve(record, **payload):
        target.write_text("newer", encoding="utf-8")
        return True

    gateway, workspace_id = _gateway(tmp_path, mutate_then_approve, audits)
    with pytest.raises(OmnigentError) as exc_info:
        await gateway.write_file(
            session_id="conv_owner",
            workspace_id=workspace_id,
            path="note.txt",
            content="stale replacement",
            mode=PolicyMode.MANUAL,
        )
    assert exc_info.value.code == ErrorCode.CONFLICT
    assert target.read_text(encoding="utf-8") == "newer"
    assert audits[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_denied_shell_never_starts_and_preview_hides_arguments(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    captured = []
    audits = []

    async def deny(record, **payload):
        captured.append(payload)
        return False

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("shell process must not start after denial")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", unexpected_spawn)
    gateway, workspace_id = _gateway(tmp_path, deny, audits)
    secret = "Bearer secret-value"
    with pytest.raises(OmnigentError):
        await gateway.run_shell(
            session_id="conv_owner",
            workspace_id=workspace_id,
            command=f'curl -H "Authorization: {secret}" https://example.invalid',
            cwd=".",
            mode=PolicyMode.MANUAL,
        )
    assert captured[0]["command_preview"] == "curl [arguments hidden]"
    assert secret not in str(captured[0])
    assert captured[0]["shell_guarantee"] == "trusted_machine"
    assert [event["status"] for event in audits] == ["requested", "denied"]
    assert all(event["command_summary"] == "curl [arguments hidden]" for event in audits)
    assert secret not in str(audits)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_pending_resolution_is_at_most_once() -> None:
    pending_approvals.reset_for_tests()
    future = pending_approvals.register("elic_once")
    try:
        assert pending_approvals.resolve("elic_once", True) is True
        assert pending_approvals.resolve("elic_once", True) is False
        assert await future is True
    finally:
        pending_approvals.cleanup("elic_once")
        pending_approvals.reset_for_tests()


@pytest.mark.asyncio
async def test_runner_app_emits_nested_local_action_and_writes_once(tmp_path) -> None:
    """The production approval producer sends only the typed nested payload."""

    class _Response:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"elicitation_id": "elicit_app_write"}

        def raise_for_status(self) -> None:
            return None

    class _ServerClient:
        def __init__(self) -> None:
            self.posts: list[tuple[str, dict[str, Any]]] = []

        async def post(self, path: str, **kwargs: Any) -> _Response:
            self.posts.append((path, kwargs["json"]))
            return _Response()

    pending_approvals.reset_for_tests()
    server = _ServerClient()
    app = create_runner_app(
        server_client=server,  # type: ignore[arg-type]
        runner_workspace=tmp_path,
        per_session_workspace=False,
    )
    workspace = app.state.local_action_gateway._workspaces.advertise(home=tmp_path)[0]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        request = asyncio.create_task(
            client.post(
                "/v1/runner/local-actions",
                json={
                    "session_id": "conv_app_write",
                    "workspace_id": workspace["workspace_id"],
                    "kind": "write_file",
                    "path": "approved.txt",
                    "content": "approved once\n",
                    "policy_mode": "manual",
                },
            )
        )
        for _ in range(100):
            if pending_approvals.has_pending("conv_app_write"):
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("runner never parked the local action")

        path, event = server.posts[0]
        assert path == "/v1/sessions/conv_app_write/events"
        assert set(event["data"]) == {"message", "requestedSchema", "local_action"}
        local_action = event["data"]["local_action"]
        assert local_action["version"] == 1
        assert local_action["kind"] == "write_file"
        assert local_action["path_summary"] == ["approved.txt"]
        assert local_action["diff_preview"].startswith("--- a/approved.txt")

        assert pending_approvals.resolve("elicit_app_write", True) is True
        assert pending_approvals.resolve("elicit_app_write", True) is False
        response = await asyncio.wait_for(request, timeout=1.0)

    assert response.status_code == 200, response.text
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "approved once\n"
    pending_approvals.reset_for_tests()
