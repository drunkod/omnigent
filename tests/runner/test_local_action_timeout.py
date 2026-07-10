"""Timeout-specific tests for T05 local action gateway/dispatch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from omnigent.errors import ErrorCode
from omnigent.policies.types import PolicyMode
from omnigent.runner import local_actions as local_actions_mod
from omnigent.runner.local_actions import LocalActionGateway, LocalActionTimeoutError
from omnigent.runner.tool_dispatch import execute_tool, reset_local_runner_binding_cache
from omnigent.runner.workspace_registry import WorkspaceRegistry
from omnigent.tools.builtins.os_env import SysOsShellTool


@pytest.fixture(autouse=True)
def _reset_binding_cache() -> None:
    reset_local_runner_binding_cache()
    yield
    reset_local_runner_binding_cache()


class _FakeTimeoutProc:
    """Fake subprocess that never completes communicate before timeout."""

    pid = 4242
    returncode: int | None = None

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(3600)
        return b"", b""

    async def wait(self) -> int:
        self.returncode = -9
        return self.returncode


def _make_gateway(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise(home=tmp_path)[0]["workspace_id"])
    audits: list[dict[str, object]] = []

    def publish(record) -> None:
        audits.append(dict(record.to_event()))

    async def approve(record, **payload: object) -> bool:
        del record, payload
        return True

    gateway = LocalActionGateway(
        workspaces=registry,
        runner_id="runner_test1",
        publish_audit=publish,
        request_approval=approve,
    )
    return gateway, workspace_id, audits


def test_run_shell_timeout_raises_typed_error_and_audits_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, workspace_id, audits = _make_gateway(tmp_path)

    async def _fake_create_subprocess_shell(*_args: object, **_kwargs: object) -> _FakeTimeoutProc:
        return _FakeTimeoutProc()

    monkeypatch.setattr(local_actions_mod, "_SHELL_TIMEOUT_S", 0.001)
    fake_asyncio = SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio) if not name.startswith("__")}
    )
    fake_asyncio.create_subprocess_shell = _fake_create_subprocess_shell
    monkeypatch.setattr(local_actions_mod, "asyncio", fake_asyncio)
    monkeypatch.setattr(local_actions_mod, "_kill_process_group", lambda _pid: None)

    with pytest.raises(LocalActionTimeoutError) as excinfo:
        asyncio.run(
            gateway.run_shell(
                session_id="conv_timeout_gateway",
                workspace_id=workspace_id,
                command="sleep 999",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.INTERNAL_ERROR
    assert str(excinfo.value) == "command timed out"
    assert audits[-1]["status"] == "failed"


class _BoundSessionClient:
    """Minimal server client returning a local-runner-bound session snapshot."""

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


class _TimeoutGateway:
    async def run_shell(self, **_kwargs: Any) -> dict[str, object]:
        raise LocalActionTimeoutError()


def test_dispatch_formats_local_action_timeout_as_shell_timeout() -> None:
    conversation_id = "conv_timeout_dispatch"

    output = asyncio.run(
        execute_tool(
            tool_name=SysOsShellTool.name(),
            arguments=json.dumps({"command": "sleep 999", "cwd": "."}),
            server_client=_BoundSessionClient(),  # type: ignore[arg-type]
            conversation_id=conversation_id,
            local_action_gateway=_TimeoutGateway(),  # type: ignore[arg-type]
        )
    )

    payload = json.loads(output)
    assert payload == {
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "timed_out": True,
        "cwd": ".",
        "error": "command timed out",
    }
