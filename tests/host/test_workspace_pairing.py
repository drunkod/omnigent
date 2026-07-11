"""Tests for host workspace-pairing helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omnigent.host.workspace_pairing import (
    DEFAULT_WORKSPACE_CAPABILITIES,
    RUNNER_MODE_LOCAL,
    RUNNER_WORKSPACES_ENV_VAR,
    HostWorkspaceError,
    add_record_workspace,
    canonicalize_root,
    canonicalize_roots,
    extract_record_workspaces,
    local_readiness,
    remove_record_workspace,
    set_record_workspaces,
    stored_record_workspaces,
    workspace_display_label,
    workspace_env,
    workspace_status_rows,
)


def test_canonicalize_root_requires_existing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(HostWorkspaceError, match="existing directory"):
        canonicalize_root(missing)


def test_canonicalize_root_rejects_empty_path() -> None:
    with pytest.raises(HostWorkspaceError, match="must not be empty"):
        canonicalize_root(" ")


def test_canonicalize_roots_deduplicates_preserving_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert canonicalize_roots([first, second, first]) == [
        str(first.resolve()),
        str(second.resolve()),
    ]


def test_workspace_env_uses_pathsep(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()

    env = workspace_env((str(first), str(second)))

    assert env[RUNNER_WORKSPACES_ENV_VAR].split(os.pathsep) == [
        str(first.resolve()),
        str(second.resolve()),
    ]


def test_workspace_env_returns_empty_without_workspaces() -> None:
    assert workspace_env(()) == {}


def test_workspace_display_label_uses_relative_to_not_string_prefix(tmp_path: Path) -> None:
    home = tmp_path / "alice"
    inside = home / "project"
    sibling = tmp_path / "alice2" / "project"
    inside.mkdir(parents=True)
    sibling.mkdir(parents=True)

    assert workspace_display_label(inside, home=home) == "~/project"
    assert workspace_display_label(sibling, home=home) == sibling.resolve().as_posix()


def test_workspace_status_rows_are_sanitized_and_display_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    rows = workspace_status_rows([project], home=tmp_path)

    assert rows == [
        {
            "path": str(project.resolve()),
            "label": "~/project",
            "capabilities": list(DEFAULT_WORKSPACE_CAPABILITIES),
            "missing": False,
        }
    ]


def test_workspace_status_rows_keep_deleted_roots_visible(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    deleted = str(project.resolve())
    project.rmdir()

    rows = workspace_status_rows([deleted], home=tmp_path)

    assert rows == [
        {
            "path": deleted,
            "label": "~/project",
            "capabilities": list(DEFAULT_WORKSPACE_CAPABILITIES),
            "missing": True,
        }
    ]


def test_stored_record_workspaces_skips_missing_when_requested(tmp_path: Path) -> None:
    present = tmp_path / "present"
    deleted = tmp_path / "deleted"
    present.mkdir()
    deleted.mkdir()
    deleted_path = str(deleted.resolve())
    deleted.rmdir()

    assert stored_record_workspaces([present, deleted_path], include_missing=False) == [
        str(present.resolve())
    ]


def test_extract_record_workspaces_ignores_malformed_entries() -> None:
    record = {"workspaces": ["/a", "", None, 7, " /b "]}

    assert extract_record_workspaces(record) == ["/a", " /b "]


def test_set_record_workspaces_persists_runner_mode_and_canonical_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record: dict[str, object] = {"pid": 123}

    updated = set_record_workspaces(record, [project])

    assert updated is record
    assert record["workspaces"] == [str(project.resolve())]
    assert record["runner_mode"] == RUNNER_MODE_LOCAL


def test_add_record_workspace_adds_once_and_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record: dict[str, object] = {}

    _, added, canonical = add_record_workspace(record, project)
    _, added_again, canonical_again = add_record_workspace(record, project)

    assert added is True
    assert added_again is False
    assert canonical == canonical_again == str(project.resolve())
    assert record["workspaces"] == [str(project.resolve())]
    assert record["runner_mode"] == RUNNER_MODE_LOCAL


def test_add_record_workspace_allows_missing_sibling(tmp_path: Path) -> None:
    alive = tmp_path / "alive"
    doomed = tmp_path / "doomed"
    fresh = tmp_path / "fresh"
    alive.mkdir()
    doomed.mkdir()
    fresh.mkdir()
    doomed_path = str(doomed.resolve())
    record: dict[str, object] = {
        "workspaces": [str(alive.resolve()), doomed_path],
        "runner_mode": RUNNER_MODE_LOCAL,
    }
    doomed.rmdir()

    _, added, canonical = add_record_workspace(record, fresh)

    assert added is True
    assert canonical == str(fresh.resolve())
    assert record["workspaces"] == [str(alive.resolve()), doomed_path, str(fresh.resolve())]
    assert record["runner_mode"] == RUNNER_MODE_LOCAL


def test_remove_record_workspace_removes_canonical_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    record: dict[str, object] = {}
    set_record_workspaces(record, [project, other])

    _, canonical = remove_record_workspace(record, project)

    assert canonical == str(project.resolve())
    assert record["workspaces"] == [str(other.resolve())]


def test_remove_record_workspace_allows_deleted_approved_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record = {"workspaces": [str(project.resolve())], "runner_mode": RUNNER_MODE_LOCAL}
    deleted_path = str(project.resolve())
    project.rmdir()

    _, canonical = remove_record_workspace(record, deleted_path)

    assert canonical == deleted_path
    assert record["workspaces"] == []
    assert record["runner_mode"] == RUNNER_MODE_LOCAL


def test_remove_record_workspace_fails_for_unapproved_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(HostWorkspaceError, match="not an approved workspace"):
        remove_record_workspace({}, project)


def test_local_readiness_returns_expected_probe_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/bin/" + name if name in {"tmux", "git"} else None

    monkeypatch.setattr("omnigent.host.workspace_pairing.shutil.which", fake_which)

    assert local_readiness() == {"tmux": True, "git": True, "node": False}
