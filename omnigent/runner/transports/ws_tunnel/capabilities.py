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

from omnigent.runner.transports.ws_tunnel.frames import (
    ALLOWED_HELLO_MODES,
    FRAME_PROTOCOL_VERSION,
    HelloFrame,
)

DEFAULT_TERMINAL_FEATURE_FLAGS = frozenset({"terminal-pty", "terminal-control"})
DEFAULT_TOOL_CAPABILITIES = [
    "read_file",
    "write_file",
    "list_dir",
    "search_files",
    "run_shell",
    "git_status",
    "git_diff",
]
_SUPPORTED_TMUX_PLATFORMS = {"darwin", "linux"}


class AdvertisedWorkspaceRegistry(Protocol):
    """Small protocol implemented by the T02 workspace registry."""

    def advertise(self) -> list[dict[str, Any]]:
        """Return display-only workspace summaries.

        :returns: Public workspace metadata safe to expose in a hello frame.
        """


def detect_terminal_transports(
    *,
    feature_flags: Iterable[str] | None = None,
    system: str | None = None,
    tmux_available: bool | None = None,
) -> list[str]:
    """Advertise terminal transports the runner can actually serve.

    Both MVP transports use the existing tmux-backed terminal bridges. Missing
    tmux or an unsupported platform therefore means no terminal transports are
    advertised.

    :param feature_flags: Optional feature flag names. ``None`` uses the default
        flag set that preserves current Unix/tmux attach behavior.
    :param system: Optional platform override for tests. ``None`` probes
        :func:`platform.system`.
    :param tmux_available: Optional tmux availability override for tests.
        ``None`` probes ``shutil.which("tmux")``.
    :returns: Supported terminal transports in preference order.
    """
    flags = set(DEFAULT_TERMINAL_FEATURE_FLAGS if feature_flags is None else feature_flags)
    normalized_system = (system or platform.system()).lower()
    # Re-probe on each hello so reconnects reflect live runner state (for
    # example tmux installed or removed after process start).
    tmux_ok = shutil.which("tmux") is not None if tmux_available is None else tmux_available

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
    system: str | None = None,
    tmux_available: bool | None = None,
) -> HelloFrame:
    """Build the capability-bearing hello for a runner process.

    :param runner_version: Runner version string to advertise.
    :param harnesses: Harness names this runner can spawn.
    :param envs: OS environment names this runner supports.
    :param mode: Runner placement mode. Must be one of
        :data:`ALLOWED_HELLO_MODES`.
    :param workspace_registry: Optional registry exposing display-only workspace
        summaries. Path enforcement remains runner-side.
    :param feature_flags: Optional feature flag names forwarded to
        :func:`detect_terminal_transports`.
    :param system: Optional platform override forwarded to
        :func:`detect_terminal_transports`; useful for tests.
    :param tmux_available: Optional tmux availability override forwarded to
        :func:`detect_terminal_transports`; useful for tests.
    :returns: A :class:`HelloFrame` populated with runner capability metadata.
    :raises ValueError: If *mode* is not a supported hello mode.
    """
    if mode not in ALLOWED_HELLO_MODES:
        allowed = ", ".join(sorted(ALLOWED_HELLO_MODES))
        raise ValueError(f"unsupported runner mode {mode!r}; expected one of: {allowed}")

    return HelloFrame(
        runner_version=runner_version,
        frame_protocol_version=FRAME_PROTOCOL_VERSION,
        harnesses=list(harnesses),
        envs=list(envs),
        mode=mode,
        os_name=platform.system().lower(),
        arch=platform.machine().lower(),
        workspace_roots=workspace_registry.advertise() if workspace_registry is not None else [],
        terminal_transports=detect_terminal_transports(
            feature_flags=feature_flags,
            system=system,
            tmux_available=tmux_available,
        ),
        tool_capabilities=list(DEFAULT_TOOL_CAPABILITIES),
    )
