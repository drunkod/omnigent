"""Runner-side gateway executing approved local actions in a workspace.

Every entry point takes a workspace id and workspace-relative paths.
``WorkspaceRegistry.resolve_in_workspace`` is the only path resolver used.
Every call produces an audit record, including policy blocks, user denials,
execution failures, and path-resolution failures.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runner.identity import strip_runner_auth_secrets
from omnigent.runner.workspace_policy import Decision, PolicyMode, Verdict, classify_action, classify_path
from omnigent.runner.workspace_registry import WorkspaceRegistry, WorkspaceRegistryError

_MAX_READ_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_BYTES = 256 * 1024
_SHELL_TIMEOUT_S = 600.0
_ENV_ALLOWLIST = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "SHELL"})

AuditPublisher = Callable[["AuditRecord"], None]
ApprovalRequester = Callable[["AuditRecord"], Awaitable[bool]]
PayloadApprovalRequester = Callable[..., Awaitable[bool]]


@dataclass
class AuditRecord:
    """Server-visible audit entry for one local action.

    Paths are workspace-relative. Never include absolute local paths, runner
    auth tokens, or full file contents in this record.

    :param action_id: Unique action id, e.g. ``"act_abc123"``.
    :param session_id: Session id that requested the action.
    :param runner_id: Runner id executing the action.
    :param workspace_id: Opaque workspace id.
    :param kind: Local action kind, e.g. ``"read_file"``.
    :param requested_by: ``"agent"`` or ``"user"``.
    :param policy_mode: Policy mode string.
    :param status: Audit status, e.g. ``"requested"`` or ``"completed"``.
    """

    action_id: str
    session_id: str
    runner_id: str
    workspace_id: str
    kind: str
    requested_by: str
    policy_mode: str
    status: str
    risk_flags: list[str] = field(default_factory=list)
    approval_id: str | None = None
    cwd: str = "."
    path_summary: list[str] = field(default_factory=list)
    command_summary: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    output_truncated: bool = False

    def to_event(self) -> dict[str, object]:
        """Return a JSON-compatible audit event without ``None`` fields."""

        return {key: value for key, value in self.__dict__.items() if value is not None}


def truncate_output(data: bytes) -> tuple[str, bool]:
    """Return deterministic UTF-8-safe truncated process output."""

    truncated = len(data) > _MAX_OUTPUT_BYTES
    if truncated:
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def subprocess_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the allowlisted environment for local shell actions.

    The result is additionally passed through ``strip_runner_auth_secrets`` so
    this gateway agrees with local Python tool subprocess spawning.
    """

    env = os.environ if source is None else source
    allowlisted = {key: value for key, value in env.items() if key in _ENV_ALLOWLIST}
    return strip_runner_auth_secrets(allowlisted)


class LocalActionGateway:
    """Execute local actions after policy/approval evaluation."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        runner_id: str,
        publish_audit: AuditPublisher,
        request_approval: PayloadApprovalRequester,
    ) -> None:
        """Initialize the gateway.

        :param workspaces: Runner-side workspace registry.
        :param runner_id: Current runner id.
        :param publish_audit: Callback invoked for every audit status edge.
        :param request_approval: Async callback for ASK verdicts. It receives
            the audit record and optional approval-only payload, such as a diff
            preview.
        """

        self._workspaces = workspaces
        self._runner_id = runner_id
        self._publish_audit = publish_audit
        self._request_approval = request_approval
        self._write_locks: dict[str, asyncio.Lock] = {}

    def _write_lock(self, workspace_id: str) -> asyncio.Lock:
        return self._write_locks.setdefault(workspace_id, asyncio.Lock())

    def _new_record(
        self,
        *,
        session_id: str,
        workspace_id: str,
        kind: str,
        mode: PolicyMode,
        requested_by: str = "agent",
    ) -> AuditRecord:
        return AuditRecord(
            action_id=f"act_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            runner_id=self._runner_id,
            workspace_id=workspace_id,
            kind=kind,
            requested_by=requested_by,
            policy_mode=mode.value,
            status="requested",
        )

    async def _gate(
        self,
        record: AuditRecord,
        verdict: Verdict,
        **approval_payload: object,
    ) -> None:
        """Apply a verdict: publish, optionally await approval, or raise."""

        record.risk_flags = list(verdict.risk_flags)
        if verdict.decision is Decision.BLOCK:
            record.status = "blocked"
            self._publish_audit(record)
            raise OmnigentError(verdict.reason, code=ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY)
        if verdict.decision is Decision.ASK:
            record.status = "requested"
            self._publish_audit(record)
            approved = await self._request_approval(record, **approval_payload)
            if not approved:
                record.status = "denied"
                self._publish_audit(record)
                raise OmnigentError(
                    "user denied the action",
                    code=ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL,
                )
            record.status = "approved"
            self._publish_audit(record)
            return
        record.status = "approved"

    def _resolve_or_audit(self, record: AuditRecord, path: str) -> Path:
        """Resolve a workspace-relative path and audit failures before re-raising."""

        try:
            return self._workspaces.resolve_in_workspace(record.workspace_id, path)
        except WorkspaceRegistryError as exc:
            message = str(exc)
            record.finished_at = time.time()
            if message.startswith("unknown workspace id"):
                record.status = "failed"
                self._publish_audit(record)
                raise OmnigentError(message, code=ErrorCode.WORKSPACE_NOT_FOUND) from exc
            record.status = "blocked"
            self._publish_audit(record)
            raise OmnigentError(message, code=ErrorCode.WORKSPACE_OUTSIDE_ALLOWED_ROOTS) from exc

    async def read_file(
        self,
        *,
        session_id: str,
        workspace_id: str,
        path: str,
        mode: PolicyMode,
    ) -> dict[str, object]:
        """Read a UTF-8 text file from a workspace after classification."""

        record = self._new_record(session_id=session_id, workspace_id=workspace_id, kind="read_file", mode=mode)
        record.path_summary = [path]
        await self._gate(record, classify_path("read_file", path, mode=mode))
        resolved = self._resolve_or_audit(record, path)
        record.started_at = time.time()
        if not resolved.is_file():
            record.status = "failed"
            record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError(f"not a file: {path}", code=ErrorCode.NOT_FOUND)
        if resolved.stat().st_size > _MAX_READ_BYTES:
            record.status = "failed"
            record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError("file too large to read", code=ErrorCode.INVALID_INPUT)
        content = await asyncio.to_thread(resolved.read_text, "utf-8", "replace")
        record.status = "completed"
        record.finished_at = time.time()
        self._publish_audit(record)
        return {"path": path, "content": content}

    async def list_dir(
        self,
        *,
        session_id: str,
        workspace_id: str,
        path: str,
        mode: PolicyMode,
    ) -> dict[str, object]:
        """List one workspace directory after classification."""

        record = self._new_record(session_id=session_id, workspace_id=workspace_id, kind="list_dir", mode=mode)
        record.path_summary = [path]
        await self._gate(record, classify_path("list_dir", path, mode=mode))
        resolved = self._resolve_or_audit(record, path)
        if not resolved.is_dir():
            record.status = "failed"
            record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError(f"not a directory: {path}", code=ErrorCode.NOT_FOUND)
        entries = sorted({"name": item.name, "dir": item.is_dir()} for item in resolved.iterdir())
        record.status = "completed"
        record.finished_at = time.time()
        self._publish_audit(record)
        return {"path": path, "entries": entries}

    async def write_file(
        self,
        *,
        session_id: str,
        workspace_id: str,
        path: str,
        content: str,
        mode: PolicyMode,
    ) -> dict[str, object]:
        """Write a UTF-8 text file after diff-backed approval when required."""

        record = self._new_record(session_id=session_id, workspace_id=workspace_id, kind="write_file", mode=mode)
        record.path_summary = [path]
        verdict = classify_path("write_file", path, mode=mode)
        if verdict.decision is Decision.BLOCK:
            await self._gate(record, verdict)
        resolved = self._resolve_or_audit(record, path)
        before = ""
        if resolved.is_file():
            before = await asyncio.to_thread(resolved.read_text, "utf-8", "replace")
        diff_preview = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                content.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        record.command_summary = f"write {path} ({len(content.encode())} bytes)"
        await self._gate(record, verdict, diff_preview=diff_preview[:64_000])
        async with self._write_lock(workspace_id):
            record.started_at = time.time()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(resolved.write_text, content, "utf-8")
        record.status = "completed"
        record.finished_at = time.time()
        self._publish_audit(record)
        return {"path": path, "bytes_written": len(content.encode())}

    async def run_shell(
        self,
        *,
        session_id: str,
        workspace_id: str,
        command: str,
        cwd: str = ".",
        mode: PolicyMode,
    ) -> dict[str, object]:
        """Run a shell command from a workspace-relative cwd."""

        record = self._new_record(session_id=session_id, workspace_id=workspace_id, kind="run_shell", mode=mode)
        record.command_summary = command[:400]
        record.cwd = cwd
        await self._gate(record, classify_action("run_shell", mode=mode, command=command, cwd=cwd))
        resolved_cwd = self._resolve_or_audit(record, cwd)
        record.started_at = time.time()
        record.status = "running"
        self._publish_audit(record)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(resolved_cwd),
            env=subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), _SHELL_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            _kill_process_group(proc.pid)
            await proc.wait()
            record.status = "failed"
            record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError("command timed out", code=ErrorCode.INTERNAL_ERROR) from exc
        out_text, out_truncated = truncate_output(stdout)
        err_text, err_truncated = truncate_output(stderr)
        record.exit_code = proc.returncode
        record.output_truncated = out_truncated or err_truncated
        record.status = "completed" if proc.returncode == 0 else "failed"
        record.finished_at = time.time()
        self._publish_audit(record)
        return {
            "exit_code": proc.returncode,
            "stdout": out_text,
            "stderr": err_text,
            "truncated": record.output_truncated,
            "duration_s": round(record.finished_at - record.started_at, 3),
        }


def _kill_process_group(pid: int) -> None:
    """Best-effort process-group kill used after shell timeouts."""

    if hasattr(os, "killpg"):
        os.killpg(pid, signal.SIGKILL)
    else:  # pragma: no cover - Windows fallback
        os.kill(pid, signal.SIGKILL)
