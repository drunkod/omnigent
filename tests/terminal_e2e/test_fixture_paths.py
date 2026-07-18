"""Portability checks for terminal E2E tmux socket paths."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from tests.terminal_e2e.conftest import (
    _MACOS_UNIX_SOCKET_PATH_MAX_BYTES,
)


def test_tmux_private_socket_path_fits_macos_limit(
    _tmux_temp_root: Path,
) -> None:
    """Production-shaped private paths remain valid on macOS.

    ``create_terminal_instance`` creates an ``omnigent-terminal-*``
    directory through Python's tempfile module and places ``tmux.sock``
    below it. Reproduce that shape without starting tmux so path-length
    regressions fail quickly and clearly on every platform.
    """
    private_dir = Path(
        tempfile.mkdtemp(
            prefix="omnigent-terminal-",
        )
    )

    try:
        socket_path = private_dir / "tmux.sock"
        encoded_path = os.fsencode(socket_path)

        assert private_dir.parent == _tmux_temp_root
        assert len(encoded_path) < _MACOS_UNIX_SOCKET_PATH_MAX_BYTES, (
            f"tmux socket path is too long for macOS: {len(encoded_path)} bytes: {socket_path}"
        )
    finally:
        shutil.rmtree(private_dir, ignore_errors=True)


def test_tmux_temp_environment_uses_fixture_root(
    _tmux_temp_root: Path,
) -> None:
    """Environment and Python's cached tempfile root stay synchronized."""
    assert os.environ["TMPDIR"] == str(_tmux_temp_root)
    assert os.environ["TEMP"] == str(_tmux_temp_root)
    assert os.environ["TMP"] == str(_tmux_temp_root)
    assert tempfile.gettempdir() == str(_tmux_temp_root)
