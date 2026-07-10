# T05 — Permissioned local action gateway on the runner

Implements plan `02-server-runner-work-plan.md` Tasks 4.1–4.3, `04-permissions-security-tests.md`
audit model, and checklist P7.

Ground truth (verified against current code):

- `omnigent/tools/local.py` already strips runner auth secrets before spawning tool
  subprocesses — keep and reuse that stripping helper.
- The server reaches the runner's ASGI app through `WSTunnelTransport`
  (`RunnerRouter._client_for_runner`), so new runner routes are automatically tunneled.
- Path enforcement primitives come from T02 (`WorkspaceRegistry.resolve_in_workspace`).

Two new modules, both runner-side: `omnigent/runner/workspace_policy.py`
(classification — pure, unit-testable) and `omnigent/runner/local_actions.py`
(execution + audit). The server never executes workspace file/shell work itself.

## 0. Shared enum — `omnigent/policies/types.py`

`PolicyMode` is imported by both the server policy builtins (T08) and the runner
gateway, so it lives in a dependency-free shared module — server policy registration
must never import runner execution code:

```python
"""Lightweight policy types shared by server policies and the runner gateway."""

from enum import Enum


class PolicyMode(str, Enum):
    MANUAL = "manual"      # MVP default: ask for every side effect
    ASSISTED = "assisted"  # reads free; writes/shell ask
    AUTO = "auto"          # writes free in-workspace; risky commands ask
```

## 1. `omnigent/runner/workspace_policy.py`

```python
"""Risk classification for local runner actions.

Pure functions: given an action request, decide allow / ask / block.
Approval UX and policy presets live server-side; this module is the
runner's last line of defense and must fail closed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# PolicyMode lives in the shared lightweight module (see T08 §1) so
# server policy builtins never import runner execution code. This
# module re-exports it for runner-side call sites.
from omnigent.policies.types import PolicyMode

__all__ = [
    "Decision",
    "PolicyMode",
    "Verdict",
    "classify_action",
    "classify_path",
    "classify_shell",
    "is_sensitive_path",
]


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    BLOCK = "block"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    risk_flags: tuple[str, ...]
    reason: str


# Read-only action kinds allowed without approval in every mode
# (paths are still workspace-enforced by resolve_in_workspace).
_READ_KINDS = frozenset(
    {"read_file", "list_dir", "search_files", "git_status", "git_diff"}
)
_WRITE_KINDS = frozenset({"write_file", "apply_patch"})

# Substring/regex patterns that are blocked in every mode unless the
# deployment explicitly overrides them. Mirror the plan's
# "Always block" list (04-permissions-security-tests.md).
_BLOCKED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("privilege_escalation", re.compile(r"^(sudo|doas|su)\b")),
    ("root_delete", re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+(/|~|\$HOME)(\s|$)")),
    ("chown_global", re.compile(r"\bchown\b.*\s(/|/etc|/usr)(\s|$)")),
    ("shell_profile", re.compile(r">>?\s*(~|\$HOME)/\.(bashrc|zshrc|profile|bash_profile)\b")),
    ("git_global_config", re.compile(r"\bgit\s+config\s+--global\b")),
    ("reverse_shell", re.compile(r"\b(nc|ncat|socat)\b.*\b(-e|exec:)")),
    ("curl_pipe_sh", re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(ba)?sh\b")),
)

# Sensitive path names / path segments that must never be readable/writable even
# via shell (defense in depth beyond workspace containment).
_SENSITIVE_SEGMENTS: frozenset[str] = frozenset({
    ".ssh", ".aws", ".gnupg", ".password-store",
})
_SENSITIVE_BASENAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
})
_SENSITIVE_PATH_PATTERNS: tuple[tuple[str, ...], ...] = (
    (".config", "gcloud"),
    (".kube", "config"),
)


def is_sensitive_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    parts = [p.lower() for p in Path(normalized).parts if p not in {"", "."}]
    if not parts:
        return False
    if any(part in _SENSITIVE_SEGMENTS for part in parts):
        return True
    if parts[-1] in _SENSITIVE_BASENAMES:
        return True
    return any(tuple(parts[i:i + len(pattern)]) == pattern
               for pattern in _SENSITIVE_PATH_PATTERNS
               for i in range(len(parts) - len(pattern) + 1))


def classify_path(kind: str, path: str, *, mode: PolicyMode) -> Verdict:
    """Classify a file-oriented action against sensitive-path policy."""
    if is_sensitive_path(path):
        # Safer default for MVP: block obviously secret-bearing paths regardless of mode.
        return Verdict(
            Decision.BLOCK,
            (kind, "sensitive_path"),
            f"references sensitive path: {path}",
        )
    return classify_action(kind, mode=mode)

_ASK_ALWAYS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("package_install", re.compile(r"\b(pip|pip3|npm|pnpm|yarn|uv|cargo|gem|brew|apt(-get)?)\s+(install|add)\b")),
    ("git_destructive", re.compile(r"\bgit\s+(reset\s+--hard|rebase|push\s+--force|clean\s+-[a-zA-Z]*f)")),
    ("file_removal", re.compile(r"\brm\b|\bunlink\b|\brmdir\b")),
)


def classify_shell(command: str, *, mode: PolicyMode, cwd: str | None = None) -> Verdict:
    """Classify one shell command string.

    Fail closed: anything unparseable is ASK (manual/assisted) or
    BLOCK-on-doubt patterns first.
    """
    flags: list[str] = ["shell"]
    lowered = command.strip()

    if cwd is not None and is_sensitive_path(cwd):
        return Verdict(
            Decision.BLOCK,
            ("shell", "sensitive_path"),
            f"references sensitive cwd: {cwd}",
        )

    for flag, pattern in _BLOCKED_PATTERNS:
        if pattern.search(lowered):
            return Verdict(Decision.BLOCK, ("shell", flag), f"blocked pattern: {flag}")

    for token in re.findall(r"[^\s\"']+", lowered):
        if is_sensitive_path(token):
            return Verdict(
                Decision.BLOCK, ("shell", "sensitive_path"),
                f"references sensitive path: {token}",
            )

    for flag, pattern in _ASK_ALWAYS_PATTERNS:
        if pattern.search(lowered):
            flags.append(flag)

    try:
        shlex.split(lowered)
    except ValueError:
        return Verdict(Decision.ASK, tuple(flags) + ("unparseable",), "unparseable command")

    # Shell escapes path-level containment: only cwd is resolved through
    # the workspace registry, while the command itself can reference any
    # absolute path. Without a sandbox or a path-aware parser, AUTO must
    # not auto-approve arbitrary commands — every shell action asks.
    # AUTO only widens gateway file writes (see classify_action).
    return Verdict(Decision.ASK, tuple(flags), f"{mode.value} mode: shell requires approval")


def classify_action(
    kind: str,
    *,
    mode: PolicyMode,
    command: str | None = None,
    cwd: str | None = None,
) -> Verdict:
    """Classify a gateway action by kind (see local_actions.py)."""
    if kind in _READ_KINDS:
        return Verdict(Decision.ALLOW, ("read",), "read-only inside workspace")
    if kind in _WRITE_KINDS:
        if mode is PolicyMode.AUTO:
            return Verdict(Decision.ALLOW, ("writes_files",), "auto mode: in-workspace write")
        return Verdict(Decision.ASK, ("writes_files",), f"{mode.value} mode: write requires approval")
    if kind == "run_shell":
        return classify_shell(command or "", mode=mode, cwd=cwd)
    return Verdict(Decision.BLOCK, ("unknown_kind",), f"unknown action kind: {kind!r}")
```

## 2. `omnigent/runner/local_actions.py`

```python
"""Runner-side gateway executing approved local actions in a workspace.

Every entry point takes a workspace_id and workspace-relative paths;
`WorkspaceRegistry.resolve_in_workspace` (T02) is the only path
resolver used. Every call produces an audit record.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runner.workspace_policy import (
    Decision,
    PolicyMode,
    Verdict,
    classify_action,
    classify_path,
)
from omnigent.runner.workspaces import WorkspaceRegistry

_MAX_READ_BYTES = 2 * 1024 * 1024          # refuse larger file reads
_MAX_OUTPUT_BYTES = 256 * 1024             # deterministic stdout/stderr truncation
_SHELL_TIMEOUT_S = 600.0
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "SHELL")


@dataclass
class AuditRecord:
    """Server-visible audit entry (04-permissions-security-tests.md model).

    Paths are workspace-relative; never absolute local paths, tokens,
    or full file contents.
    """

    action_id: str
    session_id: str
    runner_id: str
    workspace_id: str
    kind: str
    requested_by: str                      # "agent" | "user"
    policy_mode: str
    status: str                            # requested|approved|denied|blocked|running|completed|failed
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
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _truncate(data: bytes) -> tuple[str, bool]:
    """Deterministic UTF-8-safe truncation of process output."""
    truncated = len(data) > _MAX_OUTPUT_BYTES
    if truncated:
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def _subprocess_env() -> dict[str, str]:
    """Allowlisted env for shell actions; never runner auth secrets.

    Reuse omnigent.tools.local's secret-stripping helper on top of the
    allowlist so both layers agree.
    """
    return {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}


class LocalActionGateway:
    """Executes gateway actions after policy/approval evaluation."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceRegistry,
        runner_id: str,
        publish_audit,               # Callable[[AuditRecord], None] → session SSE
        request_approval,            # async (AuditRecord) -> bool; wires pending_approvals
    ) -> None:
        self._workspaces = workspaces
        self._runner_id = runner_id
        self._publish_audit = publish_audit
        self._request_approval = request_approval
        # Serialize writes per workspace so concurrent tool calls
        # can't interleave partial writes (plan Task 4.3 acceptance).
        self._write_locks: dict[str, asyncio.Lock] = {}

    def _write_lock(self, workspace_id: str) -> asyncio.Lock:
        return self._write_locks.setdefault(workspace_id, asyncio.Lock())

    async def _gate(self, record: AuditRecord, verdict: Verdict) -> None:
        """Apply a verdict: publish, and either pass, await approval, or raise."""
        record.risk_flags = list(verdict.risk_flags)
        if verdict.decision is Decision.BLOCK:
            record.status = "blocked"
            self._publish_audit(record)
            raise OmnigentError(verdict.reason, code=ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY)
        if verdict.decision is Decision.ASK:
            record.status = "requested"
            self._publish_audit(record)
            approved = await self._request_approval(record)
            if not approved:
                record.status = "denied"
                self._publish_audit(record)
                raise OmnigentError(
                    "user denied the action", code=ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL
                )
            record.status = "approved"
        else:
            record.status = "approved"

    def _new_record(self, *, session_id: str, workspace_id: str, kind: str,
                    mode: PolicyMode, requested_by: str = "agent") -> AuditRecord:
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

    # ── Read family ──────────────────────────────────────────

    async def read_file(self, *, session_id: str, workspace_id: str,
                        path: str, mode: PolicyMode) -> dict[str, object]:
        record = self._new_record(session_id=session_id, workspace_id=workspace_id,
                                  kind="read_file", mode=mode)
        record.path_summary = [path]
        await self._gate(record, classify_path("read_file", path, mode=mode))
        resolved = self._workspaces.resolve_in_workspace(workspace_id, path)
        record.started_at = time.time()
        if not resolved.is_file():
            record.status = "failed"; record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError(f"not a file: {path}", code=ErrorCode.NOT_FOUND)
        if resolved.stat().st_size > _MAX_READ_BYTES:
            record.status = "failed"; record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError("file too large to read", code=ErrorCode.INVALID_INPUT)
        content = await asyncio.to_thread(resolved.read_text, "utf-8", "replace")
        record.status = "completed"; record.finished_at = time.time()
        self._publish_audit(record)
        return {"path": path, "content": content}

    async def list_dir(self, *, session_id: str, workspace_id: str,
                       path: str, mode: PolicyMode) -> dict[str, object]:
        record = self._new_record(session_id=session_id, workspace_id=workspace_id,
                                  kind="list_dir", mode=mode)
        record.path_summary = [path]
        await self._gate(record, classify_path("list_dir", path, mode=mode))
        resolved = self._workspaces.resolve_in_workspace(workspace_id, path)
        entries = sorted(
            {"name": p.name, "dir": p.is_dir()} for p in resolved.iterdir()
        ) if resolved.is_dir() else []
        record.status = "completed"
        self._publish_audit(record)
        return {"path": path, "entries": entries}

    # ── Write family ─────────────────────────────────────────

    async def write_file(self, *, session_id: str, workspace_id: str, path: str,
                         content: str, mode: PolicyMode) -> dict[str, object]:
        record = self._new_record(session_id=session_id, workspace_id=workspace_id,
                                  kind="write_file", mode=mode)
        record.path_summary = [path]
        verdict = classify_path("write_file", path, mode=mode)
        if verdict.decision is Decision.BLOCK:
            await self._gate(record, verdict)

        resolved = self._workspaces.resolve_in_workspace(workspace_id, path)

        # Diff preview BEFORE approval so the card shows exactly what changes.
        before = ""
        if resolved.is_file():
            before = await asyncio.to_thread(resolved.read_text, "utf-8", "replace")
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), content.splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        ))
        record.command_summary = f"write {path} ({len(content)} bytes)"
        # The approval request carries the diff out-of-band (approval
        # payload), NOT in the audit record (no full contents server-side).
        record_extra = {"diff_preview": diff[:64_000]}

        await self._gate_with_payload(record, verdict, record_extra)

        async with self._write_lock(workspace_id):
            record.started_at = time.time()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(resolved.write_text, content, "utf-8")
        record.status = "completed"; record.finished_at = time.time()
        self._publish_audit(record)
        return {"path": path, "bytes_written": len(content.encode())}

    async def _gate_with_payload(self, record, verdict, extra: dict) -> None:
        """Same as _gate but attaches an approval-only payload (diff preview)."""
        record.risk_flags = list(verdict.risk_flags)
        if verdict.decision is Decision.BLOCK:
            record.status = "blocked"; self._publish_audit(record)
            raise OmnigentError(verdict.reason, code=ErrorCode.LOCAL_ACTION_BLOCKED_BY_POLICY)
        if verdict.decision is Decision.ASK:
            record.status = "requested"; self._publish_audit(record)
            if not await self._request_approval(record, **extra):
                record.status = "denied"; self._publish_audit(record)
                raise OmnigentError("user denied the action",
                                    code=ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL)
            record.status = "approved"
        else:
            record.status = "approved"

    # ── Shell ────────────────────────────────────────────────

    async def run_shell(self, *, session_id: str, workspace_id: str, command: str,
                        cwd: str = ".", mode: PolicyMode) -> dict[str, object]:
        record = self._new_record(session_id=session_id, workspace_id=workspace_id,
                                  kind="run_shell", mode=mode)
        record.command_summary = command[:400]
        record.cwd = cwd
        await self._gate(
            record,
            classify_action("run_shell", mode=mode, command=command, cwd=cwd),
        )

        resolved_cwd = self._workspaces.resolve_in_workspace(workspace_id, cwd)
        record.started_at = time.time()
        record.status = "running"
        self._publish_audit(record)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(resolved_cwd),
            env=_subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), _SHELL_TIMEOUT_S)
        except asyncio.TimeoutError:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            record.status = "failed"; record.finished_at = time.time()
            self._publish_audit(record)
            raise OmnigentError("command timed out", code=ErrorCode.INTERNAL_ERROR)
        out_text, out_trunc = _truncate(stdout)
        err_text, err_trunc = _truncate(stderr)
        record.exit_code = proc.returncode
        record.output_truncated = out_trunc or err_trunc
        record.status = "completed" if proc.returncode == 0 else "failed"
        record.finished_at = time.time()
        self._publish_audit(record)
        return {
            "exit_code": proc.returncode,
            "stdout": out_text, "stderr": err_text,
            "truncated": record.output_truncated,
            "duration_s": round(record.finished_at - record.started_at, 3),
        }
```

`search_files`, `apply_patch`, `git_status`, `git_diff` follow the same skeleton:
resolve → classify → gate → execute → audit. For file-oriented actions, classification
must flow through `classify_path(...)` so `read_file`, `list_dir`, `write_file`,
`apply_patch`, and `search_files` share the same sensitive-path guard. For `write_file`
and `apply_patch`, classify first, block immediately if needed, then compute the diff
preview and call `_gate_with_payload(...)` exactly once so the user sees the proposed
change before the only approval prompt. `apply_patch` computes the unified diff preview
from the patch itself and applies with `git apply --index --directory` pinned to the
workspace root; `git_*` run through `run_shell`'s subprocess path with
`classify_action("git_status", ...)` (ALLOW).

Implementation note (review follow-up): several methods call `resolve_in_workspace(...)`
after the gate; wrap `WorkspaceEscapeError` / unknown-workspace errors so they publish a
`blocked` (escape) or `failed` (invalid workspace) audit event before re-raising — the
"every action emits an audit record" rule includes path-resolution failures.

## 3. Runner routes — `omnigent/runner/app.py`

```python
from omnigent.runner.local_actions import LocalActionGateway
from omnigent.runner.workspace_policy import PolicyMode
from pydantic import BaseModel


class LocalActionRequest(BaseModel):
    session_id: str
    workspace_id: str
    kind: str                          # read_file | write_file | ... | run_shell
    path: str | None = None
    content: str | None = None
    command: str | None = None
    cwd: str = "."
    policy_mode: PolicyMode = PolicyMode.MANUAL


@app.post("/v1/runner/local-actions")
async def execute_local_action(body: LocalActionRequest) -> dict[str, object]:
    """Tunnel-reachable gateway endpoint used by server tool routing."""
    gw: LocalActionGateway = app.state.local_action_gateway
    dispatch = {
        "read_file": lambda: gw.read_file(session_id=body.session_id,
            workspace_id=body.workspace_id, path=body.path or "", mode=body.policy_mode),
        "list_dir": lambda: gw.list_dir(session_id=body.session_id,
            workspace_id=body.workspace_id, path=body.path or ".", mode=body.policy_mode),
        "write_file": lambda: gw.write_file(session_id=body.session_id,
            workspace_id=body.workspace_id, path=body.path or "",
            content=body.content or "", mode=body.policy_mode),
        "run_shell": lambda: gw.run_shell(session_id=body.session_id,
            workspace_id=body.workspace_id, command=body.command or "",
            cwd=body.cwd, mode=body.policy_mode),
        # + search_files / apply_patch / git_status / git_diff
    }
    handler = dispatch.get(body.kind)
    if handler is None:
        raise OmnigentError(f"unknown action kind: {body.kind!r}",
                            code=ErrorCode.INVALID_INPUT)
    return await handler()
```

Approval wiring: `request_approval` bridges to the existing
`omnigent/runner/pending_approvals.py` flow (the same pending-approval machinery
native harness ask-gates use), so approvals surface as the standard approval cards and
`_forward_approval_to_runner` in `sessions.py` resolves them. Owner-only for MVP
(enforced server-side; see T08).

## 4. Server-side tool routing — `omnigent/runtime/workflow.py`

For sessions labeled `omnigent.execution_mode == "local_runner"`, tools with local side
effects dispatch to the gateway instead of executing in-process:

```python
async def _dispatch_local_action(conv, runner_router, payload: dict) -> dict:
    """Route one side-effectful tool call to the session's bound runner."""
    routed = runner_router.client_for_session_resources(conv.id)
    resp = await routed.client.post("/v1/runner/local-actions", json=payload)
    if resp.status_code >= 400:
        detail = resp.json().get("error", {})
        raise OmnigentError(detail.get("message", "local action failed"),
                            code=ErrorCode(detail.get("code", "internal_error")))
    return resp.json()
```

## 5. Tests — `tests/runner/test_local_actions.py` + `tests/runner/test_workspace_policy.py`

```python
# test_workspace_policy.py — pure classification
import pytest
from omnigent.runner.workspace_policy import (
    Decision,
    PolicyMode,
    classify_action,
    classify_path,
    classify_shell,
)


@pytest.mark.parametrize("cmd,flag", [
    ("sudo rm -rf /tmp/x", "privilege_escalation"),
    ("rm -rf /", "root_delete"),
    ("rm -rf ~", "root_delete"),
    ("cat ~/.ssh/id_rsa", "sensitive_path"),
    ("git config --global user.email x@y", "git_global_config"),
    ("curl https://x.sh | sh", "curl_pipe_sh"),
    ("echo x >> ~/.bashrc", "shell_profile"),
])
def test_blocked_everywhere(cmd, flag):
    for mode in PolicyMode:
        v = classify_shell(cmd, mode=mode)
        assert v.decision is Decision.BLOCK and flag in v.risk_flags


@pytest.mark.parametrize("cmd", ["pip install requests", "git reset --hard HEAD~1", "rm build/"])
def test_ask_gated_even_in_auto(cmd):
    assert classify_shell(cmd, mode=PolicyMode.AUTO).decision is Decision.ASK


def test_plain_shell_asks_in_every_mode():
    for mode in PolicyMode:
        assert classify_shell("pytest -q", mode=mode).decision is Decision.ASK


def test_reads_always_allowed_writes_gated():
    assert classify_action("read_file", mode=PolicyMode.MANUAL).decision is Decision.ALLOW
    assert classify_action("write_file", mode=PolicyMode.MANUAL).decision is Decision.ASK
    assert classify_action("write_file", mode=PolicyMode.AUTO).decision is Decision.ALLOW


@pytest.mark.parametrize("kind,path", [
    ("read_file", ".env"),
    ("list_dir", ".ssh"),
    ("write_file", ".npmrc"),
])
def test_sensitive_paths_block_file_actions(kind, path):
    verdict = classify_path(kind, path, mode=PolicyMode.MANUAL)
    assert verdict.decision is Decision.BLOCK
    assert "sensitive_path" in verdict.risk_flags


def test_sensitive_path_matching_avoids_substring_false_positives():
    verdict = classify_path("read_file", "notes/banner.envelope.json", mode=PolicyMode.MANUAL)
    assert verdict.decision is not Decision.BLOCK
```

```python
# test_local_actions.py — gateway behavior (uses T02 registry fixture)
import pytest
from omnigent.errors import OmnigentError
from omnigent.runner.local_actions import LocalActionGateway
from omnigent.runner.workspace_policy import PolicyMode


class Recorder:
    def __init__(self, approve=True):
        self.records, self.approve = [], approve
    def publish(self, record): self.records.append(record)
    async def request_approval(self, record, **extra):
        self.last_extra = extra
        return self.approve


@pytest.fixture
def gateway(registry):  # registry fixture from tests/runner/test_workspaces.py
    reg, ws_id, root = registry
    rec = Recorder()
    gw = LocalActionGateway(workspaces=reg, runner_id="runner_t",
                            publish_audit=rec.publish,
                            request_approval=rec.request_approval)
    return gw, rec, ws_id, root


async def test_read_inside_ok(gateway):
    gw, rec, ws_id, _ = gateway
    out = await gw.read_file(session_id="conv_1", workspace_id=ws_id,
                             path="src/app.py", mode=PolicyMode.MANUAL)
    assert "print" in out["content"]
    assert rec.records[-1].status == "completed"


async def test_read_traversal_blocked(gateway):
    gw, _, ws_id, _ = gateway
    with pytest.raises(OmnigentError):
        await gw.read_file(session_id="conv_1", workspace_id=ws_id,
                           path="../secret", mode=PolicyMode.MANUAL)


async def test_read_sensitive_file_blocked(gateway):
    gw, _, ws_id, root = gateway
    (root / ".env").write_text("TOKEN=secret\n")
    with pytest.raises(OmnigentError):
        await gw.read_file(session_id="conv_1", workspace_id=ws_id,
                           path=".env", mode=PolicyMode.MANUAL)


async def test_list_dir_sensitive_path_blocked(gateway):
    gw, _, ws_id, root = gateway
    (root / ".ssh").mkdir()
    with pytest.raises(OmnigentError):
        await gw.list_dir(session_id="conv_1", workspace_id=ws_id,
                          path=".ssh", mode=PolicyMode.MANUAL)


async def test_write_manual_requires_approval_and_has_diff(gateway):
    gw, rec, ws_id, root = gateway
    await gw.write_file(session_id="conv_1", workspace_id=ws_id,
                        path="src/app.py", content="print('bye')\n",
                        mode=PolicyMode.MANUAL)
    assert "diff_preview" in rec.last_extra
    assert "-print('hi')" in rec.last_extra["diff_preview"]
    assert (root / "src" / "app.py").read_text() == "print('bye')\n"


async def test_denied_write_does_not_execute(gateway):
    gw, rec, ws_id, root = gateway
    rec.approve = False
    with pytest.raises(OmnigentError):
        await gw.write_file(session_id="conv_1", workspace_id=ws_id,
                            path="src/app.py", content="x", mode=PolicyMode.MANUAL)
    assert (root / "src" / "app.py").read_text() == "print('hi')\n"
    assert rec.records[-1].status == "denied"


async def test_shell_cwd_escape_blocked(gateway):
    gw, _, ws_id, _ = gateway
    with pytest.raises(OmnigentError):
        await gw.run_shell(session_id="conv_1", workspace_id=ws_id,
                           command="ls", cwd="../..", mode=PolicyMode.AUTO)


async def test_shell_timeout_kills_process_group(gateway, monkeypatch):
    gw, _, ws_id, _ = gateway
    killed = []
    monkeypatch.setattr("omnigent.runner.local_actions._SHELL_TIMEOUT_S", 0.5)
    real_killpg = os.killpg
    monkeypatch.setattr(
        "omnigent.runner.local_actions.os.killpg",
        lambda pid, sig: (killed.append((pid, sig)), real_killpg(pid, sig))[1],
    )
    with pytest.raises(OmnigentError):
        await gw.run_shell(
            session_id="conv_1",
            workspace_id=ws_id,
            command="python -c \"import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)\"",
            cwd=".",
            mode=PolicyMode.AUTO,
        )
    assert killed, "timeout must kill the spawned process group, not only the shell"


async def test_shell_env_is_allowlisted(gateway, monkeypatch):
    gw, rec, ws_id, _ = gateway
    monkeypatch.setenv("OMNIGENT_RUNNER_TOKEN", "supersecret")
    out = await gw.run_shell(session_id="conv_1", workspace_id=ws_id,
                             command="env", cwd=".", mode=PolicyMode.AUTO)
    assert "supersecret" not in out["stdout"]


async def test_large_output_truncated_deterministically(gateway):
    gw, _, ws_id, _ = gateway
    out = await gw.run_shell(session_id="conv_1", workspace_id=ws_id,
                             command="yes x | head -c 400000", cwd=".",
                             mode=PolicyMode.AUTO)
    assert out["truncated"] is True
    assert len(out["stdout"].encode()) <= 256 * 1024
```

## Acceptance checklist

- [ ] Classification blocks the plan's "always block" list in every mode; ask-gates
      installs/destructive git/removals even in auto; allows reads everywhere.
- [ ] Gateway: all paths via `resolve_in_workspace`; file actions additionally pass the
      shared sensitive-path guard with path-segment matching (no substring false
      positives); shell cwd is classified pre-approval and forced in-workspace; env
      allowlisted + secret-stripped; deterministic truncation; per-workspace write lock.
- [ ] Diff preview attached to approval payload, not to server-visible audit; writes and
      patches ask at most once, and only after the preview is available.
- [ ] Denied/blocked actions never touch disk; shell timeout kills the full process group;
      every action emits an audit record.
- [ ] Approval flow reuses `pending_approvals` and existing approval cards.
- [ ] All tests above pass.
