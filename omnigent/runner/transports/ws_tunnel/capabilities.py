"""Capability helpers for runner tunnel hello frames.

This module is intentionally side-effect free: callers pass in the runner's
known harness/env lists and optional workspace registry, and the helper returns
a capability-bearing :class:`HelloFrame` without opening files, sockets, or
spawning terminal processes.
"""

from __future__ import annotations

import platform
import shutil
from collections.abc import Iterable
from typing import Any, Protocol

from omnigent.runner.transports.ws_tunnel.frames import HelloFrame

FRAME_PROTOCOL_VERSION = 1
DEFAULT_TERMINAL_FEATURE_FLAGS = frozenset({"terminal-pty", "terminal-control"})
DEFAULT_TOOL_CAPABILITIES = [
    "read_file",
    "write_file",
    "list_dir",
    "search_files",
    "apply_patch",
    "run_shell",
    "git_status",
    "git_diff",
]
_SUPPORTED_TMUX_PLATFORMS = {"darwin", "linux"}


class AdvertisedWorkspaceRegistry(Protocol):
    """Small protocol implemented by the T02 workspace registry."""

    def advertise(self) -> list[dict[str, Any]]:
        """Return display-only workspace summaries."""


_DETECT_TMUX = object()


def detect_terminal_transports(
    *,
    feature_flags: Iterable[str] | None = None,
    system: str | None = None,
    tmux_path: str | None | object = _DETECT_TMUX,
) -> list[str]:
    """Advertise terminal transports the runner can actually serve.

    Both MVP transports use the existing tmux-backed terminal bridges. Missing
    tmux or an unsupported platform therefore means no terminal transports are
    advertised. ``tmux_path`` is injectable for tests; pass ``None`` to force
    absent tmux, a non-empty string to force present tmux, or leave it unset to
    probe ``shutil.which("tmux")``.
    """

    flags = set(DEFAULT_TERMINAL_FEATURE_FLAGS if feature_flags is None else feature_flags)
    normalized_system = (system or platform.system()).lower()
    tmux_ok = shutil.which("tmux") is not None if tmux_path is _DETECT_TMUX else bool(tmux_path)

    if normalized_system not in _SUPPORTED_TMUX_PLATFORMS or not tmux_ok:
        return []

    transports: list[str] = []
    if "terminal-pty" in flags:
        transports.append("pty")
    if "terminal-control" in flags:
        transports.append("control")
    return transports


def build_hello(
    *,
    runner_version: str,
    harnesses: Iterable[str],
    envs: Iterable[str],
    mode: str,
    workspace_registry: AdvertisedWorkspaceRegistry | None = None,
    feature_flags: Iterable[str] | None = None,
) -> HelloFrame:
    """Build the capability-bearing hello for a runner process."""

    return HelloFrame(
        runner_version=runner_version,
        frame_protocol_version=FRAME_PROTOCOL_VERSION,
        harnesses=list(harnesses),
        envs=list(envs),
        mode=mode,
        os_name=platform.system().lower(),
        arch=platform.machine().lower(),
        workspace_roots=workspace_registry.advertise() if workspace_registry is not None else [],
        terminal_transports=detect_terminal_transports(feature_flags=feature_flags),
        tool_capabilities=list(DEFAULT_TOOL_CAPABILITIES),
    )
