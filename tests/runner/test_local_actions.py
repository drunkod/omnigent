"""Tests for T05 runner local action gateway core."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runner.identity import RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR
from omnigent.runner.local_actions import (
    LocalActionGateway,
    subprocess_env,
    truncate_output,
)
from omnigent.runner.workspace_policy import PolicyMode
from omnigent.runner.workspace_registry import WorkspaceRegistry


def _make_gateway(tmp_path: Path, *, approval: bool = True):
    root = tmp_path / "workspace"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise(home=tmp_path)[0]["workspace_id"])
    audits: list[dict[str, object]] = []
    approval_payloads: list[dict[str, object]] = []

    def publish(record) -> None:
        audits.append(dict(record.to_event()))

    async def request_approval(record, **payload: object) -> bool:
        approval_payloads.append({"record": record.to_event(), **payload})
        return approval

    gateway = LocalActionGateway(
        workspaces=registry,
        runner_id="runner_test1",
        publish_audit=publish,
        request_approval=request_approval,
    )
    return gateway, workspace_id, root, audits, approval_payloads


def test_read_file_allowed_and_audited(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    result = asyncio.run(
        gateway.read_file(
            session_id="conv_test1",
            workspace_id=workspace_id,
            path="hello.txt",
            mode=PolicyMode.MANUAL,
        )
    )

    assert result == {"path": "hello.txt", "content": "hello"}
    assert audits[-1]["status"] == "completed"
    assert audits[-1]["path_summary"] == ["hello.txt"]


def test_list_dir_sorts_multiple_entries_by_name(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "sub").mkdir()

    result = asyncio.run(
        gateway.list_dir(
            session_id="conv_test1",
            workspace_id=workspace_id,
            path=".",
            mode=PolicyMode.AUTO,
        )
    )

    assert result == {
        "path": ".",
        "entries": [
            {"name": "a.txt", "dir": False},
            {"name": "b.txt", "dir": False},
            {"name": "sub", "dir": True},
        ],
    }
    assert audits[-1]["status"] == "completed"


def test_list_dir_not_directory_is_not_found(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root / "file.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.list_dir(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path="file.txt",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.NOT_FOUND
    assert audits[-1]["status"] == "failed"


def test_list_dir_sensitive_directory_blocks_before_resolution(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root / ".ssh").mkdir()

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.list_dir(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path=".ssh",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY
    assert audits[-1]["status"] == "blocked"
    assert "sensitive_path" in audits[-1]["risk_flags"]


def test_write_file_manual_requests_approval_with_diff_and_writes(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, approvals = _make_gateway(tmp_path, approval=True)
    (root / "demo.txt").write_text("before\n", encoding="utf-8")

    result = asyncio.run(
        gateway.write_file(
            session_id="conv_test1",
            workspace_id=workspace_id,
            path="demo.txt",
            content="after\n",
            mode=PolicyMode.MANUAL,
        )
    )

    assert result == {
        "path": "demo.txt",
        "bytes_written": len(b"after\n"),
        "created": False,
    }
    assert (root / "demo.txt").read_text(encoding="utf-8") == "after\n"
    assert [audit["status"] for audit in audits] == ["requested", "approved", "completed"]
    assert "-before" in str(approvals[0]["diff_preview"])
    assert "+after" in str(approvals[0]["diff_preview"])


def test_write_file_denial_does_not_write(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path, approval=False)

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.write_file(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path="demo.txt",
                content="blocked\n",
                mode=PolicyMode.MANUAL,
            )
        )

    assert excinfo.value.code == ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL
    assert not (root / "demo.txt").exists()
    assert [audit["status"] for audit in audits] == ["requested", "denied"]


def test_write_file_fails_if_target_changes_while_approval_pending(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "demo.txt").write_text("before\n", encoding="utf-8")
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise(home=tmp_path)[0]["workspace_id"])
    audits: list[dict[str, object]] = []

    def publish(record) -> None:
        audits.append(dict(record.to_event()))

    async def request_approval(record, **payload: object) -> bool:
        del record, payload
        (root / "demo.txt").write_text("external change\n", encoding="utf-8")
        return True

    gateway = LocalActionGateway(
        workspaces=registry,
        runner_id="runner_test1",
        publish_audit=publish,
        request_approval=request_approval,
    )

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.write_file(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path="demo.txt",
                content="after\n",
                mode=PolicyMode.MANUAL,
            )
        )

    assert excinfo.value.code == ErrorCode.CONFLICT
    assert (root / "demo.txt").read_text(encoding="utf-8") == "external change\n"
    assert [audit["status"] for audit in audits] == ["requested", "approved", "failed"]


def test_sensitive_path_blocks_before_resolution(tmp_path: Path) -> None:
    gateway, workspace_id, _root, audits, _ = _make_gateway(tmp_path)

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.read_file(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path=".env",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY
    assert audits[-1]["status"] == "blocked"
    assert "sensitive_path" in audits[-1]["risk_flags"]


def test_parent_traversal_escape_is_audited_as_blocked(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root.parent / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.read_file(
                session_id="conv_test1",
                workspace_id=workspace_id,
                path="../secret.txt",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.WORKSPACE_OUTSIDE_ALLOWED_ROOTS
    assert audits[-1]["status"] == "blocked"
    assert audits[-1]["path_summary"] == ["../secret.txt"]


def test_unknown_workspace_is_audited_as_failed(tmp_path: Path) -> None:
    gateway, _workspace_id, _root, audits, _ = _make_gateway(tmp_path)

    with pytest.raises(OmnigentError) as excinfo:
        asyncio.run(
            gateway.read_file(
                session_id="conv_test1",
                workspace_id="ws_missing",
                path="hello.txt",
                mode=PolicyMode.AUTO,
            )
        )

    assert excinfo.value.code == ErrorCode.WORKSPACE_NOT_FOUND
    assert audits[-1]["status"] == "failed"
    assert audits[-1]["workspace_id"] == "ws_missing"


def test_subprocess_env_filters_and_strips_runner_auth_secret() -> None:
    env = subprocess_env(
        {
            "PATH": "/bin",
            "HOME": "/home/test",
            "CUSTOM_SECRET": "keep-out",
            RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: "token",
        }
    )

    assert env == {"PATH": "/bin", "HOME": "/home/test"}


def test_truncate_output_is_utf8_safe() -> None:
    text, truncated = truncate_output("snowman ☃".encode())

    assert text == "snowman ☃"
    assert truncated is False


def test_audit_record_to_event_omits_none_fields(tmp_path: Path) -> None:
    gateway, workspace_id, root, audits, _ = _make_gateway(tmp_path)
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    asyncio.run(
        gateway.read_file(
            session_id="conv_test1",
            workspace_id=workspace_id,
            path="hello.txt",
            mode=PolicyMode.AUTO,
        )
    )

    assert "approval_id" not in audits[-1]
    assert "exit_code" not in audits[-1]
