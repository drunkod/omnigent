"""Capability helpers for runner tunnel hello frames.

The helper normally discovers the runner's approved workspace registry from the
process environment because the production tunnel caller has no separate
registry parameter. Supplying ``workspace_registry`` preserves the caller's
explicit capability fixture without probing or mutating process workspace state.
"""

from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from omnigent.harness_aliases import is_native_harness
from omnigent.runner.identity import RUNNER_WORKSPACE_ENV_VAR
from omnigent.runner.transports.ws_tunnel.frames import (
    ALLOWED_HELLO_MODES,
    FRAME_PROTOCOL_VERSION,
    HelloFrame,
)
from omnigent.runner.workspace_registry import WorkspaceRegistry

DEFAULT_TERMINAL_FEATURE_FLAGS = frozenset({"terminal-pty", "terminal-control"})
DEFAULT_TOOL_CAPABILITIES = [
    "read_file",
    "write_file",
    "list_dir",
    "run_shell",
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


def _default_workspace_registry() -> WorkspaceRegistry:
    """Return the production runner workspace registry from environment wiring."""

    return WorkspaceRegistry.from_env()


def _native_workspace_ready(registry: WorkspaceRegistry) -> bool:
    """Return whether legacy native terminals have one unambiguous local cwd.

    Native terminal launch still reads ``OMNIGENT_RUNNER_WORKSPACE`` while the
    public session API binds with an opaque ``workspace_id``. Until the runner
    has a per-session workspace-id resolver, advertising a native harness for a
    multi-root registry can launch it in the wrong directory. For exactly one
    runner-owned root, seed the legacy environment variable before any session
    starts. A conflicting pre-existing value fails closed.
    """

    if len(registry) != 1:
        return False
    root = next(iter(registry)).root.resolve()
    configured = os.environ.get(RUNNER_WORKSPACE_ENV_VAR)
    if configured is None:
        os.environ[RUNNER_WORKSPACE_ENV_VAR] = str(root)
        return True
    try:
        return Path(configured.strip()).expanduser().resolve() == root
    except (OSError, RuntimeError, ValueError):
        return False


def _advertised_harnesses(
    harnesses: Iterable[str],
    *,
    native_workspace_ready: bool,
) -> list[str]:
    """Return truthful harness capability names for this runner process."""

    result: list[str] = []
    codex_binary_ready = shutil.which("codex") is not None
    for harness in harnesses:
        if is_native_harness(harness) and not native_workspace_ready:
            continue
        if harness == "codex-native" and not codex_binary_ready:
            continue
        if harness not in result:
            result.append(harness)

    # The tunnel's legacy harness tuple contains the Codex SDK spelling. Add
    # the native TUI spelling only when both its binary and cwd prerequisites
    # are true, so the runner picker cannot create a session that immediately
    # fails with ``native_terminal_start_failed``.
    if "codex" in result and codex_binary_ready and native_workspace_ready:
        result.append("codex-native")
    return result


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
        summaries. When omitted, load the production registry from runner
        environment wiring and apply native-launch readiness filtering. When
        supplied, preserve the caller's advertised harness list unchanged.
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

    if workspace_registry is None:
        registry: AdvertisedWorkspaceRegistry = _default_workspace_registry()
        advertised_harnesses = _advertised_harnesses(
            harnesses,
            native_workspace_ready=_native_workspace_ready(registry),
        )
    else:
        registry = workspace_registry
        advertised_harnesses = list(harnesses)

    return HelloFrame(
        runner_version=runner_version,
        frame_protocol_version=FRAME_PROTOCOL_VERSION,
        harnesses=advertised_harnesses,
        envs=list(envs),
        mode=mode,
        os_name=platform.system().lower(),
        arch=platform.machine().lower(),
        workspace_roots=registry.advertise(),
        terminal_transports=detect_terminal_transports(
            feature_flags=feature_flags,
            system=system,
            tmux_available=tmux_available,
        ),
        tool_capabilities=list(DEFAULT_TOOL_CAPABILITIES),
    )
