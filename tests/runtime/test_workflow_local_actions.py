"""Tests for local-runner local-action workflow dispatch."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runtime.workflow import _dispatch_local_action


class _FakeRunnerClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, *, json: dict[str, Any], **_: Any) -> httpx.Response:
        self.calls.append((path, json))
        return self.response


class _FakeRouter:
    def __init__(self, client: _FakeRunnerClient) -> None:
        self.client = client
        self.session_ids: list[str] = []

    def client_for_session_resources(self, conversation_id: str) -> Any:
        self.session_ids.append(conversation_id)
        return type("_Routed", (), {"client": self.client})()


@pytest.mark.asyncio
async def test_dispatch_local_action_posts_to_runner_and_returns_json() -> None:
    payload = {"kind": "read_file", "path": "demo.txt"}
    response = httpx.Response(
        200,
        json={"path": "demo.txt", "content": "hello"},
        request=httpx.Request("POST", "http://runner/v1/runner/local-actions"),
    )
    client = _FakeRunnerClient(response)
    router = _FakeRouter(client)

    result = await _dispatch_local_action("conv_test1", router, payload)

    assert result == {"path": "demo.txt", "content": "hello"}
    assert router.session_ids == ["conv_test1"]
    assert client.calls == [("/v1/runner/local-actions", payload)]


@pytest.mark.asyncio
async def test_dispatch_local_action_maps_runner_error_payload() -> None:
    response = httpx.Response(
        403,
        json={
            "error": {
                "code": ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY,
                "message": "blocked by policy",
            }
        },
        request=httpx.Request("POST", "http://runner/v1/runner/local-actions"),
    )
    client = _FakeRunnerClient(response)
    router = _FakeRouter(client)

    with pytest.raises(OmnigentError) as excinfo:
        await _dispatch_local_action("conv_test1", router, {"kind": "write_file"})

    assert excinfo.value.code == ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY
    assert "blocked by policy" in str(excinfo.value)
