"""Tests for the T02 runner workspace registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from omnigent.runner.workspace_registry import (
    DEFAULT_WORKSPACE_CAPABILITIES,
    WorkspaceRegistry,
    WorkspaceRegistryError,
    WorkspaceRoot,
    workspace_id_for_root,
)


def test_workspace_root_from_path_derives_stable_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    first = WorkspaceRoot.from_path(root)
    second = WorkspaceRoot.from_path(root)

    assert first.workspace_id == second.workspace_id
    assert first.workspace_id == workspace_id_for_root(root)
    assert first.root == root.resolve()
    assert first.display_name == "project"
    assert first.capabilities == DEFAULT_WORKSPACE_CAPABILITIES


def test_workspace_root_path_label_uses_relative_to_not_string_prefix(tmp_path: Path) -> None:
    home = tmp_path / "alice"
    sibling = tmp_path / "alice2" / "project"
    inside = home / "project"
    home.mkdir()
    sibling.mkdir(parents=True)
    inside.mkdir()

    inside_root = WorkspaceRoot.from_path(inside)
    sibling_root = WorkspaceRoot.from_path(sibling)

    assert inside_root.path_label(home=home) == "~/project"
    assert sibling_root.path_label(home=home) == sibling.resolve().as_posix()


def test_workspace_root_path_label_for_home_itself(tmp_path: Path) -> None:
    home = tmp_path / "alice"
    home.mkdir()
    root = WorkspaceRoot.from_path(home)

    assert root.path_label(home=home) == "~"


def test_workspace_root_advertise_excludes_absolute_root(tmp_path: Path) -> None:
    root_path = tmp_path / "project"
    root_path.mkdir()
    root = WorkspaceRoot.from_path(
        root_path,
        display_name="Demo",
        capabilities=("read", "git"),
    )

    advertised = root.advertise(home=tmp_path)

    assert advertised == {
        "workspace_id": root.workspace_id,
        "display_name": "Demo",
        "path_label": "~/project",
        "capabilities": ["read", "git"],
    }
    assert "root" not in advertised


def test_workspace_root_rejects_empty_path() -> None:
    with pytest.raises(WorkspaceRegistryError, match="must not be empty"):
        WorkspaceRoot.from_path("")


def test_workspace_root_rejects_missing_directory_by_default(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(WorkspaceRegistryError, match="existing directory"):
        WorkspaceRoot.from_path(missing)


def test_workspace_root_can_allow_missing_directory_for_deferred_setup(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    root = WorkspaceRoot.from_path(missing, require_existing=False)

    assert root.root == missing.resolve()


def test_workspace_root_rejects_invalid_explicit_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(WorkspaceRegistryError, match="invalid workspace id"):
        WorkspaceRoot.from_path(root, workspace_id="project")


def test_registry_registers_and_advertises_sorted_workspaces(tmp_path: Path) -> None:
    zed = tmp_path / "zed"
    alpha = tmp_path / "alpha"
    zed.mkdir()
    alpha.mkdir()
    registry = WorkspaceRegistry.from_paths([zed, alpha])

    names = [item["display_name"] for item in registry.advertise(home=tmp_path)]

    assert names == ["alpha", "zed"]
    assert len(registry) == 2


def test_registry_is_idempotent_for_same_root_and_id(tmp_path: Path) -> None:
    root_path = tmp_path / "project"
    root_path.mkdir()
    root = WorkspaceRoot.from_path(root_path)
    registry = WorkspaceRegistry([root])

    assert registry.register(root) is root
    assert len(registry) == 1


def test_registry_rejects_same_id_for_different_root(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    registry = WorkspaceRegistry()
    registry.add_path(first, workspace_id="ws_shared")

    with pytest.raises(WorkspaceRegistryError, match="already registered"):
        registry.add_path(second, workspace_id="ws_shared")


def test_registry_rejects_same_root_for_different_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = WorkspaceRegistry()
    registry.add_path(root, workspace_id="ws_first")

    with pytest.raises(WorkspaceRegistryError, match="already registered"):
        registry.add_path(root, workspace_id="ws_second")


def test_registry_resolves_relative_paths_inside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "src"
    nested.mkdir(parents=True)
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = registry.advertise()[0]["workspace_id"]

    resolved = registry.resolve_in_workspace(str(workspace_id), "src/main.py")

    assert resolved == (root / "src" / "main.py").resolve()


def test_registry_resolve_defaults_to_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise()[0]["workspace_id"])

    assert registry.resolve_in_workspace(workspace_id) == root.resolve()


def test_registry_rejects_unknown_workspace_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])

    with pytest.raises(WorkspaceRegistryError, match="unknown workspace id"):
        registry.resolve_in_workspace("ws_missing", ".")


def test_registry_rejects_absolute_paths(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise()[0]["workspace_id"])

    with pytest.raises(WorkspaceRegistryError, match="relative"):
        registry.resolve_in_workspace(workspace_id, tmp_path / "other")


def test_registry_rejects_parent_traversal_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise()[0]["workspace_id"])

    with pytest.raises(WorkspaceRegistryError, match="escapes workspace"):
        registry.resolve_in_workspace(workspace_id, "../outside.txt")


def test_registry_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    registry = WorkspaceRegistry.from_paths([root])
    workspace_id = str(registry.advertise()[0]["workspace_id"])

    with pytest.raises(WorkspaceRegistryError, match="escapes workspace"):
        registry.resolve_in_workspace(workspace_id, "linked/secret.txt")


def test_registry_from_env_returns_empty_without_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.runner.identity import RUNNER_WORKSPACE_ENV_VAR

    monkeypatch.delenv(RUNNER_WORKSPACE_ENV_VAR, raising=False)

    registry = WorkspaceRegistry.from_env()

    assert len(registry) == 0


def test_registry_from_env_registers_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from omnigent.runner.identity import RUNNER_WORKSPACE_ENV_VAR

    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv(RUNNER_WORKSPACE_ENV_VAR, f" {root} ")

    registry = WorkspaceRegistry.from_env()

    assert len(registry) == 1
    assert registry.advertise(home=tmp_path)[0]["path_label"] == "~/project"


def test_registry_from_env_rejects_empty_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.runner.identity import RUNNER_WORKSPACE_ENV_VAR

    monkeypatch.setenv(RUNNER_WORKSPACE_ENV_VAR, "   ")

    with pytest.raises(WorkspaceRegistryError, match="must not be empty"):
        WorkspaceRegistry.from_env()
