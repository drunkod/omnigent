"""Runner-side workspace registry for local workspace roots.

The registry keeps local filesystem authority on the runner. Server-visible
metadata is display-only; all path resolution and containment checks happen
against canonical paths in this module.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_WORKSPACE_CAPABILITIES = ("read", "write", "shell", "git", "terminal")
WORKSPACE_ID_PREFIX = "ws_"


class WorkspaceRegistryError(ValueError):
    """Raised when workspace registration or path resolution fails."""


@dataclass(frozen=True)
class WorkspaceRoot:
    """Canonical runner-owned workspace root.

    :param workspace_id: Stable opaque workspace id, e.g. ``"ws_abc123"``.
    :param root: Canonical absolute root path on the runner.
    :param display_name: Human-readable project name shown in the UI.
    :param capabilities: Allowed workspace capability labels. These are
        advisory metadata; policy enforcement happens in later gateway tasks.
    """

    workspace_id: str
    root: Path
    display_name: str
    capabilities: tuple[str, ...] = field(default_factory=lambda: DEFAULT_WORKSPACE_CAPABILITIES)

    @classmethod
    def from_path(
        cls,
        root: str | os.PathLike[str],
        *,
        workspace_id: str | None = None,
        display_name: str | None = None,
        capabilities: Iterable[str] = DEFAULT_WORKSPACE_CAPABILITIES,
        require_existing: bool = True,
    ) -> "WorkspaceRoot":
        """Create a workspace record from a user-provided path.

        :param root: Workspace directory path from CLI/env/config.
        :param workspace_id: Optional explicit id. When omitted, a stable id is
            derived from the canonical root path.
        :param display_name: Optional display name. Defaults to the directory
            name, or the absolute path string for filesystem roots like ``/``.
        :param capabilities: Capability labels to advertise for this root.
        :param require_existing: Whether *root* must already be a directory.
        :returns: Canonical workspace record.
        :raises WorkspaceRegistryError: If the root is empty, not absolute after
            expansion, not an existing directory when required, or has an invalid
            id.
        """

        raw = Path(root).expanduser()
        if not str(raw).strip():
            raise WorkspaceRegistryError("workspace root must not be empty")
        canonical = raw.resolve(strict=False)
        if not canonical.is_absolute():
            raise WorkspaceRegistryError(f"workspace root must resolve to an absolute path: {root!r}")
        if require_existing and not canonical.is_dir():
            raise WorkspaceRegistryError(f"workspace root must be an existing directory: {canonical}")
        resolved_id = workspace_id or workspace_id_for_root(canonical)
        if not _valid_workspace_id(resolved_id):
            raise WorkspaceRegistryError(f"invalid workspace id: {resolved_id!r}")
        label = display_name or canonical.name or canonical.as_posix()
        return cls(
            workspace_id=resolved_id,
            root=canonical,
            display_name=label,
            capabilities=tuple(capabilities),
        )

    def path_label(self, *, home: Path | None = None) -> str:
        """Return a display-only path label for this workspace.

        Uses ``Path.relative_to`` rather than string-prefix checks so sibling
        paths such as ``/home/alice2`` are never mislabeled as inside
        ``/home/alice``.

        :param home: Optional home directory override for tests.
        :returns: ``~`` or ``~/...`` when the root is inside *home*, otherwise
            the absolute POSIX-style path string.
        """

        home_root = (home or Path.home()).expanduser().resolve(strict=False)
        try:
            relative = self.root.relative_to(home_root)
        except ValueError:
            return self.root.as_posix()
        if str(relative) == ".":
            return "~"
        return f"~/{relative.as_posix()}"

    def advertise(self, *, home: Path | None = None) -> dict[str, object]:
        """Return public workspace metadata safe for a hello frame.

        :param home: Optional home directory override for tests.
        :returns: Display-only metadata. The absolute root is intentionally not
            included.
        """

        return {
            "workspace_id": self.workspace_id,
            "display_name": self.display_name,
            "path_label": self.path_label(home=home),
            "capabilities": list(self.capabilities),
        }


def workspace_id_for_root(root: str | os.PathLike[str]) -> str:
    """Derive a stable opaque id for a canonical workspace root.

    :param root: Absolute workspace root path.
    :returns: Stable id with :data:`WORKSPACE_ID_PREFIX`, e.g. ``"ws_3f..."``.
    """

    canonical = Path(root).expanduser().resolve(strict=False)
    digest = hashlib.sha256(os.fsencode(canonical.as_posix())).hexdigest()[:16]
    return f"{WORKSPACE_ID_PREFIX}{digest}"


class WorkspaceRegistry:
    """In-memory registry of runner-owned workspace roots."""

    def __init__(self, roots: Iterable[WorkspaceRoot] = ()) -> None:
        """Initialize the registry.

        :param roots: Existing workspace records to register.
        :raises WorkspaceRegistryError: If ids or canonical roots conflict.
        """

        self._by_id: dict[str, WorkspaceRoot] = {}
        self._id_by_root: dict[Path, str] = {}
        for root in roots:
            self.register(root)

    @classmethod
    def from_paths(
        cls,
        roots: Iterable[str | os.PathLike[str]],
        *,
        capabilities: Iterable[str] = DEFAULT_WORKSPACE_CAPABILITIES,
        require_existing: bool = True,
    ) -> "WorkspaceRegistry":
        """Build a registry from path values.

        :param roots: Workspace root paths.
        :param capabilities: Capability labels to advertise for each root.
        :param require_existing: Whether paths must exist as directories.
        :returns: Workspace registry.
        """

        registry = cls()
        for root in roots:
            registry.add_path(root, capabilities=capabilities, require_existing=require_existing)
        return registry

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        require_existing: bool = True,
    ) -> "WorkspaceRegistry":
        """Build a registry from runner process environment wiring.

        :param env: Environment mapping. Defaults to :data:`os.environ`.
        :param require_existing: Whether the configured root must exist.
        :returns: Empty registry when no workspace env var is set; otherwise a
            registry containing that single root.
        :raises WorkspaceRegistryError: If the env var is present but empty or
            invalid.
        """

        from omnigent.runner.identity import RUNNER_WORKSPACE_ENV_VAR

        source = os.environ if env is None else env
        raw = source.get(RUNNER_WORKSPACE_ENV_VAR)
        if raw is None:
            return cls()
        if not raw.strip():
            raise WorkspaceRegistryError(f"{RUNNER_WORKSPACE_ENV_VAR} must not be empty")
        return cls.from_paths([raw], require_existing=require_existing)

    def register(self, root: WorkspaceRoot) -> WorkspaceRoot:
        """Register an already-created workspace root.

        Idempotent for the same id/root pair.

        :param root: Workspace record.
        :returns: The registered record.
        :raises WorkspaceRegistryError: If an id maps to a different root or a
            root maps to a different id.
        """

        existing_for_id = self._by_id.get(root.workspace_id)
        if existing_for_id is not None:
            if existing_for_id.root != root.root:
                raise WorkspaceRegistryError(
                    f"workspace id {root.workspace_id!r} already registered for {existing_for_id.root}"
                )
            return existing_for_id
        existing_id_for_root = self._id_by_root.get(root.root)
        if existing_id_for_root is not None and existing_id_for_root != root.workspace_id:
            raise WorkspaceRegistryError(
                f"workspace root {root.root} already registered as {existing_id_for_root!r}"
            )
        self._by_id[root.workspace_id] = root
        self._id_by_root[root.root] = root.workspace_id
        return root

    def add_path(
        self,
        root: str | os.PathLike[str],
        *,
        workspace_id: str | None = None,
        display_name: str | None = None,
        capabilities: Iterable[str] = DEFAULT_WORKSPACE_CAPABILITIES,
        require_existing: bool = True,
    ) -> WorkspaceRoot:
        """Create and register a workspace path.

        :param root: Workspace directory path.
        :param workspace_id: Optional explicit workspace id.
        :param display_name: Optional display name.
        :param capabilities: Capability labels.
        :param require_existing: Whether *root* must exist as a directory.
        :returns: The registered workspace record.
        """

        return self.register(
            WorkspaceRoot.from_path(
                root,
                workspace_id=workspace_id,
                display_name=display_name,
                capabilities=capabilities,
                require_existing=require_existing,
            )
        )

    def get(self, workspace_id: str) -> WorkspaceRoot | None:
        """Return a workspace by id.

        :param workspace_id: Workspace id.
        :returns: Workspace record, or ``None`` when absent.
        """

        return self._by_id.get(workspace_id)

    def require(self, workspace_id: str) -> WorkspaceRoot:
        """Return a workspace by id or raise.

        :param workspace_id: Workspace id.
        :returns: Workspace record.
        :raises WorkspaceRegistryError: If the id is unknown.
        """

        root = self.get(workspace_id)
        if root is None:
            raise WorkspaceRegistryError(f"unknown workspace id: {workspace_id!r}")
        return root

    def advertise(self, *, home: Path | None = None) -> list[dict[str, object]]:
        """Return public metadata for all registered workspaces.

        :param home: Optional home directory override for tests.
        :returns: Workspace summaries sorted by display name then id.
        """

        return [
            root.advertise(home=home)
            for root in sorted(self._by_id.values(), key=lambda item: (item.display_name, item.workspace_id))
        ]

    def resolve_in_workspace(
        self,
        workspace_id: str,
        relative_path: str | os.PathLike[str] = ".",
    ) -> Path:
        """Resolve a relative path inside a registered workspace.

        :param workspace_id: Workspace id.
        :param relative_path: Relative path requested by an agent/tool. Absolute
            paths are rejected; callers should identify roots via *workspace_id*.
        :returns: Canonical path contained within the workspace root.
        :raises WorkspaceRegistryError: If the workspace is unknown, the path is
            absolute, or resolution escapes the root, including via symlinks.
        """

        root = self.require(workspace_id)
        requested = Path(relative_path)
        if requested.is_absolute():
            raise WorkspaceRegistryError("workspace paths must be relative")
        resolved = (root.root / requested).resolve(strict=False)
        if not resolved.is_relative_to(root.root):
            raise WorkspaceRegistryError(
                f"path escapes workspace {workspace_id!r}: {relative_path!r}"
            )
        return resolved

    def __len__(self) -> int:
        """Return the number of registered workspaces."""

        return len(self._by_id)

    def __iter__(self) -> Iterable[WorkspaceRoot]:
        """Iterate over registered workspace records."""

        return iter(self._by_id.values())


def _valid_workspace_id(value: str) -> bool:
    """Return whether *value* is an accepted workspace id.

    :param value: Candidate id.
    :returns: ``True`` for opaque ids like ``ws_abc123``.
    """

    if not value.startswith(WORKSPACE_ID_PREFIX):
        return False
    suffix = value[len(WORKSPACE_ID_PREFIX) :]
    return bool(suffix) and all(ch.isalnum() or ch in {"_", "-"} for ch in suffix)
