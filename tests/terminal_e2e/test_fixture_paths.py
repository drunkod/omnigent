"""Portability checks for terminal E2E tmux socket paths."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import omnigent.inner.terminal as terminal_mod
from tests.terminal_e2e.conftest import (
    _MACOS_UNIX_SOCKET_PATH_MAX_BYTES,
)


def test_production_tmux_socket_path_fits_macos_limit(
    _tmux_temp_root: Path,
) -> None:
    """The actual production directory-selection path remains short."""
    private_dir = Path(
        tempfile.mkdtemp(
            prefix=terminal_mod._TERMINAL_DIR_PREFIX,
            dir=str(terminal_mod._terminals_tmp_root()),
        )
    )

    try:
        socket_path = (private_dir / "tmux.sock").resolve()
        encoded_path = os.fsencode(socket_path)

        assert terminal_mod._terminals_tmp_root() == _tmux_temp_root
        assert private_dir.parent == _tmux_temp_root
        assert len(encoded_path) < _MACOS_UNIX_SOCKET_PATH_MAX_BYTES, (
            f"tmux socket path is too long for macOS: {len(encoded_path)} bytes: {socket_path}"
        )
    finally:
        shutil.rmtree(private_dir, ignore_errors=True)


def test_tmux_temp_environment_uses_fixture_root(
    _tmux_temp_root: Path,
) -> None:
    """Environment, tempfile cache, and production resolver stay aligned."""
    assert os.environ["TMPDIR"] == str(_tmux_temp_root)
    assert os.environ["TEMP"] == str(_tmux_temp_root)
    assert os.environ["TMP"] == str(_tmux_temp_root)
    assert tempfile.gettempdir() == str(_tmux_temp_root)
    assert terminal_mod._terminals_tmp_root() == _tmux_temp_root
