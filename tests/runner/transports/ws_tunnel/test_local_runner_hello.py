"""Regression tests for production local-runner hello discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omnigent.runner.identity import (
    RUNNER_WORKSPACE_ENV_VAR,
    RUNNER_WORKSPACES_ENV_VAR,
)
from omnigent.runner.transports.ws_tunnel import capabilities as capabilities_module
from omnigent.runner.transports.ws_tunnel.capabilities import build_hello
from omnigent.runner.transports.ws_tunnel.frames import HelloFrame


def _build() -> HelloFrame:
    return build_hello(
        runner_version="test",
        harnesses=["claude-native", "codex"],
        envs=["os_sandbox"],
        mode="local",
        system="linux",
        tmux_available=True,
    )


def test_default_hello_preserves_legacy_harnesses_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_WORKSPACES_ENV_VAR, raising=False)
    monkeypatch.delenv(RUNNER_WORKSPACE_ENV_VAR, raising=False)
    monkeypatch.setattr(capabilities_module.shutil, "which", lambda _command: None)

    hello = _build()

    assert hello.workspace_roots == []
    assert hello.harnesses == ["claude-native", "codex"]
    assert RUNNER_WORKSPACE_ENV_VAR not in os.environ


def test_default_hello_advertises_single_env_workspace_and_native_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv(RUNNER_WORKSPACES_ENV_VAR, str(root))
    monkeypatch.delenv(RUNNER_WORKSPACE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        capabilities_module.shutil,
        "which",
        lambda command: "/usr/bin/codex" if command == "codex" else None,
    )

    hello = _build()

    assert [workspace["workspace_id"] for workspace in hello.workspace_roots]
    assert hello.workspace_roots[0]["display_name"] == "repo"
    assert "claude-native" in hello.harnesses
    assert "codex-native" in hello.harnesses
    assert os.environ[RUNNER_WORKSPACE_ENV_VAR] == str(root.resolve())


def test_default_hello_does_not_advertise_native_codex_without_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv(RUNNER_WORKSPACES_ENV_VAR, str(root))
    monkeypatch.delenv(RUNNER_WORKSPACE_ENV_VAR, raising=False)
    monkeypatch.setattr(capabilities_module.shutil, "which", lambda _command: None)

    hello = _build()

    assert "codex" in hello.harnesses
    assert "codex-native" not in hello.harnesses


def test_default_hello_blocks_native_harnesses_for_ambiguous_multi_root_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv(RUNNER_WORKSPACES_ENV_VAR, os.pathsep.join((str(first), str(second))))
    monkeypatch.delenv(RUNNER_WORKSPACE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        capabilities_module.shutil,
        "which",
        lambda command: "/usr/bin/codex" if command == "codex" else None,
    )

    hello = _build()

    assert len(hello.workspace_roots) == 2
    assert "codex" in hello.harnesses
    assert "claude-native" not in hello.harnesses
    assert "codex-native" not in hello.harnesses
    assert RUNNER_WORKSPACE_ENV_VAR not in os.environ


def test_default_hello_fails_closed_on_conflicting_legacy_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "approved"
    stale = tmp_path / "stale"
    approved.mkdir()
    stale.mkdir()
    monkeypatch.setenv(RUNNER_WORKSPACES_ENV_VAR, str(approved))
    monkeypatch.setenv(RUNNER_WORKSPACE_ENV_VAR, str(stale))
    monkeypatch.setattr(
        capabilities_module.shutil,
        "which",
        lambda command: "/usr/bin/codex" if command == "codex" else None,
    )

    hello = _build()

    assert len(hello.workspace_roots) == 1
    assert "claude-native" not in hello.harnesses
    assert "codex-native" not in hello.harnesses
    assert os.environ[RUNNER_WORKSPACE_ENV_VAR] == str(stale)
