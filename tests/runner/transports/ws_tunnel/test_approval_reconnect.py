"""T12 acceptance for runner-local approval across tunnel generations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from omnigent.runner import create_runner_app, pending_approvals
from omnigent.runner.transports.ws_tunnel.frames import HelloFrame
from omnigent.runner.transports.ws_tunnel.transport import WSTunnelTransport
from tests.runner.transports.ws_tunnel.helpers import run_tunnel_harness


class _ApprovalServerClient:
    """Capture the runner's elicitation POST and return a stable correlation id."""

    def __init__(self) -> None:
        self.elicitation_seen = asyncio.Event()
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        body = kwargs.get("json")
        assert isinstance(body, dict)
        self.posts.append((path, body))
        request = httpx.Request("POST", f"http://server{path}")
        if body.get("type") == "mcp_elicitation":
            self.elicitation_seen.set()
            return httpx.Response(
                200,
                json={"elicitation_id": "elicit_t12_reconnect"},
                request=request,
            )
        return httpx.Response(204, request=request)


class _HarnessClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        body = kwargs.get("json")
        assert isinstance(body, dict)
        self.posts.append((path, body))
        request = httpx.Request("POST", f"http://harness{path}")
        return httpx.Response(204, request=request)


class _ProcessManager:
    """Minimal live-harness facade required by the runner control-event route."""

    def __init__(self) -> None:
        self.client = _HarnessClient()

    def has_active_turn(self, _session_id: str) -> bool:
        return False

    async def get_client(self, _session_id: str, _harness: str) -> _HarnessClient:
        return self.client


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_pending_local_action_executes_once_after_runner_tunnel_reconnect(
    tmp_path: Path,
) -> None:
    """A verdict delivered on the new generation resolves one parked write once."""

    pending_approvals.reset_for_tests()
    server = _ApprovalServerClient()
    process_manager = _ProcessManager()
    runner_app = create_runner_app(  # type: ignore[arg-type]
        server_client=server,
        process_manager=process_manager,
        runner_workspace=tmp_path,
        per_session_workspace=False,
    )
    audits: list[dict[str, object]] = []
    runner_app.state.local_action_gateway._publish_audit = (  # noqa: SLF001
        lambda record: audits.append(record.to_event())
    )
    workspace = (  # noqa: SLF001
        runner_app.state.local_action_gateway._workspaces.advertise(home=tmp_path)[0]
    )
    workspace_id = workspace["workspace_id"]
    assert isinstance(workspace_id, str)

    runner_id = "runner-t12-approval"
    hello = HelloFrame(
        runner_version="t12-test",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["caller_process"],
        tool_capabilities=["write_file"],
    )
    target = tmp_path / "approved-after-reconnect.txt"

    try:
        async with run_tunnel_harness(
            runner_app,
            runner_id=runner_id,
            hello=hello,
        ) as tunnel:
            old_transport = WSTunnelTransport(tunnel.registry, runner_id)
            async with httpx.AsyncClient(
                transport=old_transport,
                base_url="http://runner",
            ) as old_client:
                action_task = asyncio.create_task(
                    old_client.post(
                        "/v1/runner/local-actions",
                        json={
                            "session_id": "conv_t12_approval",
                            "workspace_id": workspace_id,
                            "kind": "write_file",
                            "path": target.name,
                            "content": "approved exactly once\n",
                            "policy_mode": "manual",
                        },
                    )
                )
                await asyncio.wait_for(server.elicitation_seen.wait(), timeout=2.0)
                await _wait_until(
                    lambda: pending_approvals.has_pending("conv_t12_approval")
                )
                assert not target.exists()

                await tunnel.disconnect()
                result = await asyncio.gather(action_task, return_exceptions=True)
                assert isinstance(result[0], (httpx.TransportError, ConnectionError))

            tunnel.reconnect()
            new_transport = WSTunnelTransport(tunnel.registry, runner_id)
            async with httpx.AsyncClient(
                transport=new_transport,
                base_url="http://runner",
            ) as new_client:
                verdict = {
                    "type": "approval",
                    "data": {
                        "elicitation_id": "elicit_t12_reconnect",
                        "action": "accept",
                    },
                }
                first = await new_client.post(
                    "/v1/sessions/conv_t12_approval/events",
                    json=verdict,
                )
                replay = await new_client.post(
                    "/v1/sessions/conv_t12_approval/events",
                    json=verdict,
                )
                assert first.status_code == 204, first.text
                assert replay.status_code == 204, replay.text

            await _wait_until(target.exists)
            await _wait_until(
                lambda: any(event.get("status") == "completed" for event in audits)
            )

        assert target.read_text(encoding="utf-8") == "approved exactly once\n"
        statuses = [event["status"] for event in audits]
        assert statuses == ["requested", "approved", "completed"]
        local_action_posts = [
            body for _path, body in server.posts if body.get("type") == "mcp_elicitation"
        ]
        assert len(local_action_posts) == 1
    finally:
        pending_approvals.reset_for_tests()
