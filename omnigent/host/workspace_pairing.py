"""Host workspace-pairing helpers for local runner approvals.

This module is deliberately side-effect-light and shared by the Click host
commands plus daemon-spawn code. It canonicalizes user-approved workspace roots,
encodes them for the runner process environment, and mutates daemon-record JSON
payloads without ever logging or exposing tunnel-binding tokens.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from omnigent.runner.identity import RUNNER_WORKSPACES_ENV_VAR

RUNNER_MODE_LOCAL = "local"
DEFAULT_WORKSPACE_CAPABILITIES = ("read", "write", "shell", "git", "terminal")


class HostWorkspaceError(ValueError):
    """Raised when workspace pairing input or persisted state is invalid."""


def _normalize_root_path(path: str | os.PathLike[str]) -> Path:
    """Return an absolute normalized workspace path without existence checks."""

    raw_text = os.fspath(path)
    if not str(raw_text).strip():
        raise HostWorkspaceError("workspace path must not be empty")
    return Path(raw_text).expanduser().resolve(strict=False)


def canonicalize_root(path: str | os.PathLike[str]) -> Path:
    """Return the canonical approved workspace root.

    :param path: User-provided workspace directory, e.g. ``"~/project"``.
    :returns: Absolute, resolved workspace directory path.
    :raises HostWorkspaceError: If *path* is empty or not an existing directory.
    """

    root = _normalize_root_path(path)
    if not root.is_dir():
        raise HostWorkspaceError(f"workspace path must be an existing directory: {root}")
    return root


def canonicalize_roots(paths: Iterable[str | os.PathLike[str]]) -> list[str]:
    """Canonicalize and deduplicate workspace root paths preserving order.

    :param paths: Workspace paths from CLI flags or a daemon record.
    :returns: Canonical absolute root path strings.
    :raises HostWorkspaceError: If any path is invalid.
    """

    seen: set[str] = set()
    roots: list[str] = []
    for path in paths:
        canonical = str(canonicalize_root(path))
        if canonical in seen:
            continue
        seen.add(canonical)
        roots.append(canonical)
    return roots


def stored_record_workspaces(
    workspaces: Iterable[str | os.PathLike[str]],
    *,
    include_missing: bool = True,
) -> list[str]:
    """Normalize stored workspace roots without bricking on deleted dirs.

    :param workspaces: Stored workspace values from daemon-record state.
    :param include_missing: When ``True``, keep deleted/missing directories in the
        returned list so status can still surface them. When ``False``, skip
        paths that no longer exist.
    :returns: Deduplicated absolute path strings.
    """

    seen: set[str] = set()
    roots: list[str] = []
    for path in workspaces:
        try:
            normalized = str(_normalize_root_path(path))
        except HostWorkspaceError:
            continue
        if not include_missing and not Path(normalized).is_dir():
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(normalized)
    return roots


def workspace_env(workspaces: Iterable[str | os.PathLike[str]]) -> dict[str, str]:
    """Encode approved workspaces for the runner process environment.

    :param workspaces: Workspace paths approved by the local user.
    :returns: Empty dict when no workspaces are approved, otherwise a dict with
        :data:`RUNNER_WORKSPACES_ENV_VAR` containing an ``os.pathsep``-joined
        list of canonical roots.
    """

    roots = canonicalize_roots(workspaces)
    if not roots:
        return {}
    return {RUNNER_WORKSPACES_ENV_VAR: os.pathsep.join(roots)}


def local_readiness() -> dict[str, bool]:
    """Return cheap local tool-readiness probes for ``omnigent host status``.

    :returns: Availability booleans for required local runner tools.
    """

    return {
        "tmux": shutil.which("tmux") is not None,
        "git": shutil.which("git") is not None,
        "node": shutil.which("node") is not None,
    }


def workspace_display_label(path: str | os.PathLike[str], *, home: Path | None = None) -> str:
    """Return a display-only label for a canonical workspace path.

    :param path: Canonical or user-provided workspace path.
    :param home: Optional home override for tests.
    :returns: ``~``/``~/...`` when the path is inside *home*, otherwise the
        absolute POSIX-style path string.
    """

    root = Path(path).expanduser().resolve(strict=False)
    home_root = (home or Path.home()).expanduser().resolve(strict=False)
    try:
        rel = root.relative_to(home_root)
    except ValueError:
        return root.as_posix()
    if str(rel) == ".":
        return "~"
    return f"~/{rel.as_posix()}"


def workspace_status_rows(
    workspaces: Iterable[str | os.PathLike[str]],
    *,
    home: Path | None = None,
) -> list[dict[str, object]]:
    """Build human/status-friendly workspace summaries.

    :param workspaces: Workspace paths from a daemon record.
    :param home: Optional home override for tests.
    :returns: Sanitized workspace rows with labels and capability metadata.
    """

    return [
        {
            "path": root,
            "label": workspace_display_label(root, home=home),
            "capabilities": list(DEFAULT_WORKSPACE_CAPABILITIES),
            "missing": not Path(root).is_dir(),
        }
        for root in stored_record_workspaces(workspaces, include_missing=True)
    ]


def extract_record_workspaces(record: Mapping[str, Any]) -> list[str]:
    """Return valid workspace strings from a daemon-record payload.

    :param record: Decoded daemon-record mapping.
    :returns: Stored workspace path strings; malformed entries are ignored.
    """

    raw = record.get("workspaces", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item.strip()]


def set_record_workspaces(
    record: MutableMapping[str, Any],
    workspaces: Iterable[str | os.PathLike[str]],
) -> MutableMapping[str, Any]:
    """Set canonical workspace pairing fields on a daemon-record payload.

    :param record: Mutable daemon-record mapping.
    :param workspaces: Workspace roots to persist.
    :returns: The same mapping for call chaining.
    :raises HostWorkspaceError: If any workspace path is invalid.
    """

    record["workspaces"] = canonicalize_roots(workspaces)
    record["runner_mode"] = RUNNER_MODE_LOCAL
    return record


def add_record_workspace(
    record: MutableMapping[str, Any],
    path: str | os.PathLike[str],
) -> tuple[MutableMapping[str, Any], bool, str]:
    """Add one approved workspace to a daemon-record payload.

    :param record: Mutable daemon-record mapping.
    :param path: Workspace directory to approve.
    :returns: ``(record, added, canonical_path)``.
    :raises HostWorkspaceError: If *path* is invalid.
    """

    canonical = str(canonicalize_root(path))
    roots = stored_record_workspaces(extract_record_workspaces(record), include_missing=True)
    if canonical in roots:
        record["workspaces"] = roots
        record["runner_mode"] = RUNNER_MODE_LOCAL
        return record, False, canonical
    roots.append(canonical)
    record["workspaces"] = roots
    record["runner_mode"] = RUNNER_MODE_LOCAL
    return record, True, canonical


def remove_record_workspace(
    record: MutableMapping[str, Any],
    path: str | os.PathLike[str],
) -> tuple[MutableMapping[str, Any], str]:
    """Remove one approved workspace from a daemon-record payload.

    :param record: Mutable daemon-record mapping.
    :param path: Workspace directory to revoke.
    :returns: ``(record, canonical_path)``.
    :raises HostWorkspaceError: If *path* is invalid or not approved.
    """

    try:
        canonical = str(canonicalize_root(path))
    except HostWorkspaceError:
        canonical = str(_normalize_root_path(path))
    roots = stored_record_workspaces(extract_record_workspaces(record), include_missing=True)
    kept = [root for root in roots if root != canonical]
    if len(kept) == len(roots):
        raise HostWorkspaceError(f"not an approved workspace: {canonical}")
    record["workspaces"] = kept
    record["runner_mode"] = RUNNER_MODE_LOCAL
    return record, canonical
