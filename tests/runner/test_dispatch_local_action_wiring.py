"""dispatch_tool_locally must forward the local action gateway (T05)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from omnigent.policies.types import PolicyMode
from omnigent.runner.tool_dispatch import dispatch_tool_locally, reset_local_runner_binding_cache
from omnigent.tools.builtins.os_env import SysOsShellTool


class _BoundSessionClient:
    async def get(self, path: str, timeout: float | None = None) -> httpx.Response:
        del path, timeout
        return httpx.Response(
            200,
            json={
                "labels": {
                    "omnigent.execution_mode": "local_runner",
                    "omnigent.workspace_id": "ws_abc123",
                    "omnigent.local_runner_policy": PolicyMode.AUTO.value,
                }
            },
        )


class _RecordingHarnessClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(
        self, path: str, json: dict[str, Any], timeout: float | None = None
    ) -> httpx.Response:
        del timeout
        self.posts.append((path, json))
        return httpx.Response(200)


class _EchoGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_shell(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "truncated": False,
            "duration_s": 0.0,
        }


@pytest.fixture(autouse=True)
def _reset_binding_cache() -> None:
    reset_local_runner_binding_cache()
    yield
    reset_local_runner_binding_cache()


@pytest.mark.asyncio
async def test_dispatch_tool_locally_forwards_gateway_for_bound_session() -> None:
    conversation_id = "conv_dispatch_gateway_wiring"
    harness = _RecordingHarnessClient()
    gateway = _EchoGateway()

    output = await dispatch_tool_locally(
        tool_name=SysOsShellTool.name(),
        call_id="call_1",
        arguments=json.dumps({"command": "echo hi", "cwd": "."}),
        response_id="resp_1",
        harness_client=harness,  # type: ignore[arg-type]
        server_client=_BoundSessionClient(),  # type: ignore[arg-type]
        conversation_id=conversation_id,
        local_action_gateway=gateway,  # type: ignore[arg-type]
    )

    payload = json.loads(output)
    assert payload["exit_code"] == 0
    assert payload["timed_out"] is False
    assert gateway.calls and gateway.calls[0]["workspace_id"] == "ws_abc123"
    assert harness.posts and harness.posts[0][1]["call_id"] == "call_1"
    assert "gateway unavailable" not in harness.posts[0][1]["output"]
