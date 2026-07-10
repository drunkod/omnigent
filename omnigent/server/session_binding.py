"""Local-runner session binding helpers for T04.

This module owns the small, route-independent rules for binding a session to a
pre-paired local runner and one of that runner's advertised workspaces. The
server stores only opaque workspace ids and display labels; actual path
resolution and containment checks remain runner-side.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.harness_aliases import canonicalize_harness

LOCAL_RUNNER_EXECUTION_MODE = "local_runner"
EXECUTION_MODE_LABEL_KEY = "omnigent.execution_mode"
WORKSPACE_ID_LABEL_KEY = "omnigent.workspace_id"
WORKSPACE_LABEL_LABEL_KEY = "omnigent.workspace_label"
LOCAL_RUNNER_POLICY_LABEL_KEY = "omnigent.local_runner_policy"


class RunnerHelloLike(Protocol):
    """Subset of a runner hello frame used by binding validation."""

    harnesses: list[str]
    workspace_roots: list[dict[str, Any]]


class RunnerSessionLike(Protocol):
    """Subset of a live runner registry session used by binding validation."""

    owner: str | None
    hello: RunnerHelloLike


class LocalRunnerRegistryLike(Protocol):
    """Small registry protocol consumed by the binding validator."""

    def get(self, runner_id: str) -> RunnerSessionLike | None:
        """Return the live runner session for *runner_id*, if any."""


def advertised_workspace_ids(hello: RunnerHelloLike) -> set[str]:
    """Return workspace ids advertised by a runner hello.

    :param hello: Runner hello frame or test double.
    :returns: Set of non-empty ``workspace_id`` strings.
    """

    ids: set[str] = set()
    for workspace in hello.workspace_roots:
        if not isinstance(workspace, dict):
            continue
        workspace_id = workspace.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            ids.add(workspace_id)
    return ids


def advertised_workspace_label(hello: RunnerHelloLike, workspace_id: str) -> str | None:
    """Return the display-only label for an advertised workspace.

    :param hello: Runner hello frame or test double.
    :param workspace_id: Workspace id to look up, e.g. ``"ws_abc123"``.
    :returns: ``path_label`` when advertised as a string, otherwise
        ``display_name`` when present, otherwise ``None``.
    """

    for workspace in hello.workspace_roots:
        if not isinstance(workspace, dict) or workspace.get("workspace_id") != workspace_id:
            continue
        path_label = workspace.get("path_label")
        if isinstance(path_label, str) and path_label:
            return path_label
        display_name = workspace.get("display_name")
        return display_name if isinstance(display_name, str) and display_name else None
    return None


def merge_local_runner_labels(
    labels: Mapping[str, str] | None,
    *,
    runner_id: str | None,
    workspace_id: str | None,
    workspace_label: str | None,
) -> dict[str, str]:
    """Merge local-runner binding labels into caller labels.

    The workspace label is display-only. It must never be used for path
    resolution, authorization, or containment; the runner-side workspace
    registry remains authoritative.

    :param labels: Caller-supplied session labels.
    :param runner_id: Bound runner id, or ``None`` for ordinary sessions.
    :param workspace_id: Runner-advertised workspace id.
    :param workspace_label: Display-only workspace label from the runner hello.
    :returns: Merged label dictionary.
    """

    merged = dict(labels or {})
    if runner_id is None:
        return merged
    merged[EXECUTION_MODE_LABEL_KEY] = LOCAL_RUNNER_EXECUTION_MODE
    if workspace_id is not None:
        merged[WORKSPACE_ID_LABEL_KEY] = workspace_id
        if workspace_label is not None:
            merged[WORKSPACE_LABEL_LABEL_KEY] = workspace_label
    return merged


def validate_workspace_requires_runner(*, runner_id: str | None, workspace_id: str | None) -> None:
    """Validate that a workspace binding always names a runner.

    :param runner_id: Requested runner id.
    :param workspace_id: Requested workspace id.
    :raises ValueError: If *workspace_id* is set without *runner_id*.
    """

    if workspace_id is not None and runner_id is None:
        raise ValueError("workspace_id requires runner_id")


def validate_local_runner_binding(
    *,
    runner_id: str | None,
    workspace_id: str | None,
    registry: LocalRunnerRegistryLike | None,
    user_id: str | None,
    harness: str | None,
) -> RunnerSessionLike | None:
    """Validate a requested local-runner session binding.

    :param runner_id: Requested runner id, or ``None`` for unbound sessions.
    :param workspace_id: Requested runner workspace id.
    :param registry: Live tunnel registry. Required when *runner_id* is set.
    :param user_id: Authenticated caller id. ``None`` skips ownership checks.
    :param harness: Harness required by the bound session, e.g. ``"codex"``.
    :returns: The live runner session when *runner_id* is set, otherwise
        ``None``.
    :raises OmnigentError: For offline runners, ownership failures,
        harness mismatches, or unknown workspace ids.
    :raises ValueError: If *workspace_id* is set without *runner_id*.
    """

    validate_workspace_requires_runner(runner_id=runner_id, workspace_id=workspace_id)
    if runner_id is None:
        return None
    if registry is None:
        raise OmnigentError("runner tunnel registry is not configured", code=ErrorCode.INTERNAL_ERROR)
    session = registry.get(runner_id)
    if session is None:
        raise OmnigentError(
            f"runner {runner_id!r} is offline; start it with `omnigent host --server <url>` and retry",
            code=ErrorCode.RUNNER_UNAVAILABLE,
        )
    if user_id is not None and session.owner is not None and session.owner != user_id:
        raise OmnigentError("runner belongs to another user", code=ErrorCode.FORBIDDEN)
    if harness is not None and not _runner_supports_harness(session.hello, harness):
        raise OmnigentError(
            f"runner {runner_id!r} does not support harness {harness!r}",
            code=ErrorCode.RUNNER_CAPABILITY_MISMATCH,
        )
    if workspace_id is not None and workspace_id not in advertised_workspace_ids(session.hello):
        raise OmnigentError(
            f"workspace {workspace_id!r} is not advertised by runner {runner_id!r}",
            code=ErrorCode.WORKSPACE_NOT_FOUND,
        )
    return session


def runner_notification_binding_payload(labels: Mapping[str, str]) -> dict[str, str]:
    """Build non-null binding keys for the runner session-create notify.

    :param labels: Persisted session labels.
    :returns: ``workspace_id`` and/or ``execution_mode`` values when present.
        Missing labels are omitted so old/new runner skew never sees explicit
        JSON nulls for optional binding fields.
    """

    payload = {
        "workspace_id": labels.get(WORKSPACE_ID_LABEL_KEY),
        "execution_mode": labels.get(EXECUTION_MODE_LABEL_KEY),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _runner_supports_harness(hello: RunnerHelloLike, harness: str) -> bool:
    """Return whether a runner hello advertises *harness*.

    :param hello: Runner hello frame or test double.
    :param harness: Required harness kind.
    :returns: ``True`` when the exact or canonicalized harness is advertised.
    """

    canonical = canonicalize_harness(harness) or harness
    advertised: set[str] = set(_canonical_harnesses(hello.harnesses))
    return canonical in advertised or harness in advertised


def _canonical_harnesses(harnesses: Iterable[str]) -> Iterable[str]:
    """Yield advertised harnesses plus their aliases' canonical forms."""

    for harness in harnesses:
        yield harness
        canonical = canonicalize_harness(harness)
        if canonical is not None:
            yield canonical
