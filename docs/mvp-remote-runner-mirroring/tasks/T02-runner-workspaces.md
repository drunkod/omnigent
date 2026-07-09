# T02 — Runner-side workspace registry, validation, and endpoints

Implements plan `02-server-runner-work-plan.md` Tasks 2.1/2.3 and checklist P4.

Ground truth (verified against current code):

- `omnigent/runner/resource_registry.py` computes per-session workspaces from
  `OMNIGENT_RUNNER_OS_ENV_ROOT` via `_session_workspace()` and accepts a
  `runner_workspace: Path` + `per_session_workspace: bool` at construction.
- There is no user-approved multi-root workspace model yet. This task adds
  `omnigent/runner/workspaces.py` and two runner HTTP endpoints, then threads a chosen
  root into `SessionResourceRegistry`.

## 1. New module — `omnigent/runner/workspaces.py`

```python
"""User-approved local workspace roots for remote-local runner mode.

A local runner only exposes explicitly approved directory roots.
Every path the server/agent supplies is resolved and checked against
these roots on the runner — the server never enforces paths itself.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from omnigent.errors import ErrorCode, OmnigentError

_DEFAULT_CAPABILITIES = ("read", "write", "shell", "git", "terminal")
_VALIDATE_TIMEOUT_S = 5.0


class WorkspaceEscapeError(OmnigentError):
    """A path resolved outside the bound workspace root."""

    def __init__(self, message: str = "path escapes the bound workspace") -> None:
        super().__init__(message, code=ErrorCode.FORBIDDEN)


@dataclass(frozen=True)
class WorkspaceRoot:
    """One approved local workspace root.

    :param workspace_id: Stable id derived from the canonical path,
        e.g. ``"ws_1f2e3d4c5b6a"``. Stable across runner restarts so
        session bindings survive reconnects.
    :param root: Canonical absolute root, symlinks resolved.
    :param display_name: Short UI label, e.g. ``"omnigent"``.
    :param capabilities: Allowed action families for this root.
    """

    workspace_id: str
    root: Path
    display_name: str
    capabilities: tuple[str, ...] = _DEFAULT_CAPABILITIES

    @property
    def path_label(self) -> str:
        """Home-abbreviated display path, e.g. ``"~/projects/omnigent"``."""
        home = str(Path.home())
        raw = str(self.root)
        return "~" + raw[len(home):] if raw.startswith(home) else raw


def workspace_id_for_path(canonical: Path) -> str:
    """Derive the stable workspace id for a canonical path."""
    digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()[:12]
    return f"ws_{digest}"


def canonicalize_root(raw: str | Path) -> Path:
    """Expand and fully resolve a user-supplied root path.

    :raises OmnigentError: If the path does not exist or is not a
        directory (``invalid_input``).
    """
    path = Path(raw).expanduser()
    try:
        canonical = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise OmnigentError(
            f"workspace root does not exist: {path}",
            code=ErrorCode.INVALID_INPUT,
        ) from exc
    if not canonical.is_dir():
        raise OmnigentError(
            f"workspace root is not a directory: {canonical}",
            code=ErrorCode.INVALID_INPUT,
        )
    return canonical


class WorkspaceRegistry:
    """Registry of approved workspace roots for one runner process."""

    def __init__(self, roots: list[WorkspaceRoot] | None = None) -> None:
        self._roots: dict[str, WorkspaceRoot] = {
            ws.workspace_id: ws for ws in (roots or [])
        }

    @classmethod
    def from_paths(cls, paths: list[str]) -> WorkspaceRegistry:
        """Build a registry from CLI/env-provided paths (see T03)."""
        roots: list[WorkspaceRoot] = []
        for raw in paths:
            canonical = canonicalize_root(raw)
            roots.append(
                WorkspaceRoot(
                    workspace_id=workspace_id_for_path(canonical),
                    root=canonical,
                    display_name=canonical.name or str(canonical),
                )
            )
        return cls(roots)

    def list(self) -> list[WorkspaceRoot]:
        return list(self._roots.values())

    def get(self, workspace_id: str) -> WorkspaceRoot:
        """:raises OmnigentError: ``not_found`` for unknown ids."""
        ws = self._roots.get(workspace_id)
        if ws is None:
            raise OmnigentError(
                f"workspace not found: {workspace_id!r}",
                code=ErrorCode.NOT_FOUND,
            )
        return ws

    def advertise(self) -> list[dict[str, object]]:
        """Hello-frame payload (T01). Labels only — never raw secrets."""
        return [
            {
                "workspace_id": ws.workspace_id,
                "display_name": ws.display_name,
                "path_label": ws.path_label,
                "capabilities": list(ws.capabilities),
            }
            for ws in self.list()
        ]

    # ── Path enforcement (the security core) ─────────────────

    def resolve_in_workspace(self, workspace_id: str, relative: str) -> Path:
        """Resolve a workspace-relative path, refusing escapes.

        Blocks ``..`` traversal, absolute-path smuggling, and symlink
        escapes: the FINAL resolved path (after following symlinks)
        must stay under the canonical root.

        :param workspace_id: Bound workspace id, e.g. ``"ws_1f2e3d..."``.
        :param relative: Workspace-relative path, e.g. ``"src/app.py"``.
        :returns: Canonical absolute path inside the root.
        :raises WorkspaceEscapeError: On any escape attempt.
        """
        ws = self.get(workspace_id)
        if os.path.isabs(relative):
            raise WorkspaceEscapeError("absolute paths are not allowed")
        candidate = (ws.root / relative)
        # Resolve non-strictly so not-yet-existing write targets are allowed,
        # but every EXISTING ancestor has its symlinks followed.
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(ws.root)
        except ValueError as exc:
            raise WorkspaceEscapeError(
                f"path escapes workspace {ws.display_name!r}: {relative!r}"
            ) from exc
        return resolved


def validate_workspace(ws: WorkspaceRoot) -> dict[str, object]:
    """Bounded pre-bind validation and project metadata probe.

    Never traverses the tree; only cheap single-shot probes with a
    subprocess timeout so slow filesystems can't hang session create.
    """
    meta: dict[str, object] = {
        "workspace_id": ws.workspace_id,
        "display_name": ws.display_name,
        "path_label": ws.path_label,
        "exists": ws.root.is_dir(),
        "writable": os.access(ws.root, os.W_OK),
        "tmux_available": shutil.which("tmux") is not None,
        "git_available": shutil.which("git") is not None,
        "git": None,
    }
    if meta["git_available"]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(ws.root), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=_VALIDATE_TIMEOUT_S,
            )
            if proc.returncode == 0:
                dirty = subprocess.run(
                    ["git", "-C", str(ws.root), "status", "--porcelain", "--untracked-files=no"],
                    capture_output=True, text=True, timeout=_VALIDATE_TIMEOUT_S,
                )
                meta["git"] = {
                    "branch": proc.stdout.strip(),
                    "dirty": bool(dirty.stdout.strip()),
                }
        except subprocess.TimeoutExpired:
            meta["git"] = {"error": "git probe timed out"}
    return meta
```

## 2. Runner endpoints — `omnigent/runner/app.py`

Register the registry at app construction (source it from T03's CLI/env config, e.g.
`OMNIGENT_RUNNER_WORKSPACES=/path/a:/path/b`), then add:

```python
from omnigent.runner.workspaces import WorkspaceRegistry, validate_workspace

# at app build time:
workspace_registry = WorkspaceRegistry.from_paths(
    [p for p in os.environ.get("OMNIGENT_RUNNER_WORKSPACES", "").split(os.pathsep) if p]
)
app.state.workspace_registry = workspace_registry


@app.get("/v1/runner/workspaces")
async def list_workspaces() -> dict[str, list[dict[str, object]]]:
    """List approved workspace roots (labels + capabilities only)."""
    return {"data": app.state.workspace_registry.advertise()}


@app.post("/v1/runner/workspaces/{workspace_id}/validate")
async def validate_workspace_route(workspace_id: str) -> dict[str, object]:
    """Validate a workspace before session bind; bounded, no tree walk.

    :raises OmnigentError: ``not_found`` (→ 404) for unknown ids —
        the server maps this to structured code ``workspace_not_found``.
    """
    ws = app.state.workspace_registry.get(workspace_id)
    return await asyncio.to_thread(validate_workspace, ws)
```

Both endpoints are reachable from the server through the existing
`WSTunnelTransport`-backed `httpx.AsyncClient` (`RunnerRouter._client_for_runner`), so no
new transport work is needed: the server calls
`client.get("/v1/runner/workspaces")` on the routed runner.

## 3. Thread the bound root into session resources

`SessionResourceRegistry` already honors `runner_workspace` for cwd resolution. For a
session bound to `workspace_id` (binding arrives with the session snapshot — see T04),
resolve the root before creating the primary env / launching terminals:

```python
# omnigent/runner/app.py — where the session's spec/env is prepared
def _resolve_session_cwd(session_snapshot: dict[str, object]) -> Path | None:
    """Session workspace binding wins over OMNIGENT_RUNNER_WORKSPACE/temp."""
    workspace_id = session_snapshot.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id:
        ws = app.state.workspace_registry.get(workspace_id)  # raises not_found
        return ws.root
    return None  # fall back to existing behavior
```

Log the selection with the label, not the raw path:
`logger.info("session %s bound to workspace %s (%s)", sid, ws.workspace_id, ws.path_label)`.

## 4. Tests — `tests/runner/test_workspaces.py`

```python
"""Workspace registry: canonicalization + escape blocking."""

import os
from pathlib import Path

import pytest

from omnigent.errors import OmnigentError
from omnigent.runner.workspaces import (
    WorkspaceEscapeError,
    WorkspaceRegistry,
    canonicalize_root,
    workspace_id_for_path,
)


@pytest.fixture
def registry(tmp_path: Path) -> tuple[WorkspaceRegistry, str, Path]:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hi')\n")
    reg = WorkspaceRegistry.from_paths([str(root)])
    ws_id = reg.list()[0].workspace_id
    return reg, ws_id, root.resolve()


def test_workspace_id_is_stable(tmp_path: Path) -> None:
    canonical = canonicalize_root(tmp_path)
    assert workspace_id_for_path(canonical) == workspace_id_for_path(canonical)


def test_resolve_inside_ok(registry) -> None:
    reg, ws_id, root = registry
    assert reg.resolve_in_workspace(ws_id, "src/app.py") == root / "src" / "app.py"


def test_resolve_nonexistent_write_target_ok(registry) -> None:
    reg, ws_id, root = registry
    assert reg.resolve_in_workspace(ws_id, "src/new.py") == root / "src" / "new.py"


def test_dotdot_traversal_blocked(registry) -> None:
    reg, ws_id, _ = registry
    with pytest.raises(WorkspaceEscapeError):
        reg.resolve_in_workspace(ws_id, "../outside.txt")


def test_absolute_path_blocked(registry) -> None:
    reg, ws_id, _ = registry
    with pytest.raises(WorkspaceEscapeError):
        reg.resolve_in_workspace(ws_id, "/etc/passwd")


def test_symlink_escape_blocked(registry, tmp_path: Path) -> None:
    reg, ws_id, root = registry
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, root / "link")
    with pytest.raises(WorkspaceEscapeError):
        reg.resolve_in_workspace(ws_id, "link/secret.txt")


def test_unknown_workspace_id(registry) -> None:
    reg, _, _ = registry
    with pytest.raises(OmnigentError):
        reg.get("ws_nope")


def test_missing_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(OmnigentError):
        WorkspaceRegistry.from_paths([str(tmp_path / "missing")])
```

## Acceptance checklist

- [ ] Registry with stable ids; `from_paths` canonicalizes with `expanduser().resolve(strict=True)`.
- [ ] `resolve_in_workspace` blocks `..`, absolute paths, and symlink escapes (final-resolution check).
- [ ] `GET /v1/runner/workspaces` + `POST /v1/runner/workspaces/{id}/validate` reachable via tunnel.
- [ ] Validation is bounded (5s subprocess timeouts, no tree walk) and leaks no secrets.
- [ ] Session workspace binding wins over `OMNIGENT_RUNNER_WORKSPACE`/temp roots.
- [ ] All tests above pass.
