# T01 — Extend runner hello with capability fields

Implements plan `02-server-runner-work-plan.md` Task 1.1 and checklist P2.

Ground truth (verified against current code):

- `HelloFrame` lives in `omnigent/runner/transports/ws_tunnel/frames.py` (L52) with fields
  `runner_version`, `frame_protocol_version`, `harnesses`, `envs`. Frames are plain
  dataclasses with hand-rolled `encode_frame` / `decode_frame` validation.
- `TunnelRegistry.register(runner_id, ws, hello, *, owner=...)` in
  `omnigent/runner/transports/ws_tunnel/registry.py` already retains the hello on
  `RunnerSession.hello` — no registry change is needed to keep capabilities, only to expose them.
- `GET /v1/runners` and `GET /v1/runners/{id}/status` already exist in
  `omnigent/server/routes/runner_tunnel.py` and read `session.hello.harnesses`.

## 1. Frame schema changes — `omnigent/runner/transports/ws_tunnel/frames.py`

Add optional fields with safe defaults. Unknown fields in JSON are already ignored by
`decode_frame` (it only reads known keys), so **old-server/new-runner is compatible for free**;
new-server/old-runner works because all new fields default to empty.

```python
@dataclass
class HelloFrame:
    """Runner's first frame on a fresh tunnel.

    :param runner_version: Runner's semver string, e.g. ``"0.1.2"``.
    :param frame_protocol_version: Wire-protocol major. Server refuses
        on major mismatch (RUNNER.md §2 "Version skew").
    :param harnesses: Names of harness kinds the runner can spawn.
    :param envs: Names of OS env types the runner supports.
    :param mode: Execution placement: ``"local"`` (user-installed
        daemon on a trusted machine), ``"managed"`` (server-launched
        sandbox), or ``"in_process"`` (dev/test). ``None`` for
        pre-capability runners.
    :param os_name: Runner OS, e.g. ``"darwin"``/``"linux"``.
    :param arch: Runner arch, e.g. ``"arm64"``.
    :param workspace_roots: Advertised workspace summaries. Display
        metadata only — path enforcement always happens runner-side.
        Shape: ``[{"workspace_id": "ws_...", "display_name": "omnigent",
        "path_label": "~/projects/omnigent",
        "capabilities": ["read", "write", "shell", "git", "terminal"]}]``.
    :param terminal_transports: Attach transports the runner's
        terminal bridges support, subset of ``["control", "pty"]``.
    :param tool_capabilities: Local action kinds the runner will
        accept, e.g. ``["read_file", "write_file", "run_shell"]``.
    """

    runner_version: str
    frame_protocol_version: int
    harnesses: list[str] = field(default_factory=list)
    envs: list[str] = field(default_factory=list)
    # ── remote-local runner capability extension (optional) ──
    mode: str | None = None
    os_name: str | None = None
    arch: str | None = None
    workspace_roots: list[dict[str, Any]] = field(default_factory=list)
    terminal_transports: list[str] = field(default_factory=list)
    tool_capabilities: list[str] = field(default_factory=list)
```

`encode_frame` — extend the `HelloFrame` branch (omit `None`s to keep old-server logs clean):

```python
    if isinstance(frame, HelloFrame):
        payload: dict[str, Any] = {
            "kind": FrameKind.HELLO.value,
            "runner_version": frame.runner_version,
            "frame_protocol_version": frame.frame_protocol_version,
            "harnesses": list(frame.harnesses),
            "envs": list(frame.envs),
        }
        if frame.mode is not None:
            payload["mode"] = frame.mode
        if frame.os_name is not None:
            payload["os_name"] = frame.os_name
        if frame.arch is not None:
            payload["arch"] = frame.arch
        if frame.workspace_roots:
            payload["workspace_roots"] = list(frame.workspace_roots)
        if frame.terminal_transports:
            payload["terminal_transports"] = list(frame.terminal_transports)
        if frame.tool_capabilities:
            payload["tool_capabilities"] = list(frame.tool_capabilities)
        return json.dumps(payload)
```

`_decode_hello` — tolerate absence and bad types (fail-open to defaults rather than
rejecting the tunnel; a malformed capability list must not take a runner offline):

```python
_ALLOWED_MODES = ("local", "managed", "in_process")


def _decode_hello(msg: dict[str, Any]) -> HelloFrame:
    """Decode a hello frame, tolerating absent capability fields."""
    mode = msg.get("mode")
    if mode not in _ALLOWED_MODES:
        mode = None
    return HelloFrame(
        runner_version=_required_str(msg, "runner_version"),
        frame_protocol_version=_required_int(msg, "frame_protocol_version"),
        harnesses=_optional_str_list(msg, "harnesses"),
        envs=_optional_str_list(msg, "envs"),
        mode=mode,
        os_name=_lenient_optional_str(msg, "os_name"),
        arch=_lenient_optional_str(msg, "arch"),
        workspace_roots=_lenient_dict_list(msg, "workspace_roots"),
        terminal_transports=_lenient_str_list(msg, "terminal_transports"),
        tool_capabilities=_lenient_str_list(msg, "tool_capabilities"),
    )


def _lenient_optional_str(msg: dict[str, Any], key: str) -> str | None:
    """Return a string field or ``None``; never raises."""
    val = msg.get(key)
    return val if isinstance(val, str) else None


def _lenient_str_list(msg: dict[str, Any], key: str) -> list[str]:
    """Return a string-list field, dropping non-string items; never raises."""
    val = msg.get(key)
    if not isinstance(val, list):
        return []
    return [item for item in val if isinstance(item, str)]


def _lenient_dict_list(msg: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return a dict-list field, dropping non-dict items; never raises."""
    val = msg.get(key)
    if not isinstance(val, list):
        return []
    return [item for item in val if isinstance(item, dict)]
```

Note: the field is `os_name`, not `os` — avoids shadowing the `os` module in call sites
and reads unambiguously in JSON.

## 2. Runner side — populate the hello

Where the runner builds its `HelloFrame` (tunnel client in
`omnigent/runner/transports/ws_tunnel/` — locate the `HelloFrame(` construction call):

```python
import platform
import shutil

from omnigent.runner.workspaces import WorkspaceRegistry  # T02


def detect_terminal_transports(*, feature_flags: set[str] | None = None) -> list[str]:
    """Advertise only transports this runner can actually serve."""
    # Default to today's working attach behavior unless explicitly disabled:
    # both transports rely on the tmux-backed terminal bridge, so no tmux
    # means no advertised terminal transport.
    flags = feature_flags or {"terminal-pty", "terminal-control"}
    system = platform.system().lower()
    tmux_ok = shutil.which("tmux") is not None

    transports: list[str] = []
    if tmux_ok and system in {"darwin", "linux"}:
        if "terminal-pty" in flags:
            transports.append("pty")
        if "terminal-control" in flags:
            transports.append("control")
    return transports


def build_hello(
    *,
    runner_version: str,
    harnesses: list[str],
    envs: list[str],
    workspace_registry: WorkspaceRegistry | None,
    mode: str,
    feature_flags: set[str] | None = None,
) -> HelloFrame:
    """Build the capability-bearing hello for this runner process."""
    return HelloFrame(
        runner_version=runner_version,
        frame_protocol_version=1,
        harnesses=harnesses,
        envs=envs,
        mode=mode,
        os_name=platform.system().lower(),      # "darwin" / "linux" / "windows"
        arch=platform.machine().lower(),        # "arm64" / "x86_64"
        workspace_roots=(
            workspace_registry.advertise() if workspace_registry is not None else []
        ),
        terminal_transports=detect_terminal_transports(feature_flags=feature_flags),
        tool_capabilities=[
            "read_file", "write_file", "list_dir", "search_files",
            "apply_patch", "run_shell", "git_status", "git_diff",
        ],
    )
```

Do **not** advertise `terminal_transports` unconditionally. Compute them from platform,
`tmux` availability, and feature flags. In the current design both `pty` and `control`
ride the tmux-backed terminal bridge, so missing `tmux` should yield `[]`. The default
flag set should preserve today's working attach behavior on supported Unix platforms;
`[]` should happen only on genuinely unsupported environments or when tmux is absent.

Never put raw secrets, tokens, or full home paths into `workspace_roots` — use
`path_label` with `~`-abbreviated display strings (see T02 `advertise()`).

## 3. Server side — expose capabilities

`omnigent/server/routes/runner_tunnel.py`, in `list_runners` and `runner_status`,
enrich responses from the retained hello:

```python
def _capability_summary(hello: HelloFrame) -> dict[str, object]:
    """Public capability view of a runner hello (no secrets, labels only)."""
    return {
        "mode": hello.mode,
        "os": hello.os_name,
        "arch": hello.arch,
        "harnesses": list(hello.harnesses),
        "terminal_transports": list(hello.terminal_transports),
        "tool_capabilities": list(hello.tool_capabilities),
        "workspaces": [
            {
                "workspace_id": ws.get("workspace_id"),
                "display_name": ws.get("display_name"),
                "path_label": ws.get("path_label"),
                "capabilities": ws.get("capabilities", []),
            }
            for ws in hello.workspace_roots
            if isinstance(ws.get("workspace_id"), str)
        ],
    }
```

In `list_runners`, replace the bare dict with:

```python
            data.append(
                {
                    "runner_id": runner_id,
                    "online": True,
                    "runner_version": session.hello.runner_version,
                    "connected_at": session.connected_at,
                    **_capability_summary(session.hello),
                }
            )
```

In `runner_status`, when online:

```python
        if online and session is not None:
            result["runner_version"] = session.hello.runner_version
            result["capabilities"] = _capability_summary(session.hello)
```

(Keep the existing owner-scoping: capabilities are only shown for caller-owned runners;
the offline-masking branch stays untouched.)

## 4. Tests — `tests/runner/test_ws_tunnel_capabilities.py`

```python
"""Hello capability extension: encode/decode + version-skew compatibility."""

import json

from omnigent.runner.transports.ws_tunnel.frames import (
    HelloFrame,
    decode_frame,
    encode_frame,
)


def test_new_hello_roundtrip() -> None:
    frame = HelloFrame(
        runner_version="0.9.0",
        frame_protocol_version=1,
        harnesses=["codex", "claude-code"],
        envs=["posix"],
        mode="local",
        os_name="darwin",
        arch="arm64",
        workspace_roots=[
            {
                "workspace_id": "ws_abc123",
                "display_name": "omnigent",
                "path_label": "~/projects/omnigent",
                "capabilities": ["read", "write", "shell", "git", "terminal"],
            }
        ],
        terminal_transports=["pty"],
        tool_capabilities=["read_file", "run_shell"],
    )
    decoded = decode_frame(encode_frame(frame))
    assert decoded == frame


def test_old_runner_hello_decodes_with_defaults() -> None:
    """New server ← old runner: capability fields absent → defaults."""
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.1.2",
            "frame_protocol_version": 1,
            "harnesses": ["codex"],
            "envs": ["posix"],
        }
    )
    hello = decode_frame(wire)
    assert isinstance(hello, HelloFrame)
    assert hello.mode is None
    assert hello.workspace_roots == []
    assert hello.terminal_transports == []
    assert hello.tool_capabilities == []


def test_unknown_extra_fields_are_ignored() -> None:
    """Old server ← new runner: unknown keys must not break decode."""
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.9.0",
            "frame_protocol_version": 1,
            "harnesses": [],
            "envs": [],
            "some_future_field": {"x": 1},
        }
    )
    hello = decode_frame(wire)
    assert isinstance(hello, HelloFrame)


def test_malformed_capability_fields_do_not_reject_tunnel() -> None:
    """A bad capability payload degrades to defaults, never raises."""
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.9.0",
            "frame_protocol_version": 1,
            "harnesses": [],
            "envs": [],
            "mode": "evil-mode",
            "workspace_roots": "not-a-list",
            "terminal_transports": [1, 2, "pty"],
        }
    )
    hello = decode_frame(wire)
    assert isinstance(hello, HelloFrame)
    assert hello.mode is None
    assert hello.workspace_roots == []
    assert hello.terminal_transports == ["pty"]


def test_none_capabilities_omitted_from_wire() -> None:
    frame = HelloFrame(runner_version="0.1.2", frame_protocol_version=1)
    wire = json.loads(encode_frame(frame))
    assert "mode" not in wire
    assert "workspace_roots" not in wire
```

## Acceptance checklist

- [ ] `HelloFrame` extended with optional fields; defaults keep old behavior.
- [ ] Encode omits absent fields; decode is lenient (no tunnel rejection on bad capability data).
- [ ] `GET /v1/runners` and `GET /v1/runners/{id}/status` expose the capability summary,
      owner-scoped as today.
- [ ] `terminal_transports` are capability-detected from the actual runtime environment,
      never hard-coded to `['control', 'pty']`.
- [ ] Compatibility tests above pass; existing `tests/runner/test_ws_tunnel_*` untouched and green.
- [ ] No secrets/absolute-home-paths in advertised data (only `path_label`).
