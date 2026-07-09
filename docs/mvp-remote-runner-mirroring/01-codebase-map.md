# 01 — Codebase Map for Remote/Local Runner MVP

This document maps the MVP to real repository files. It is a planning artifact only.

## Current architecture facts to preserve

### Root product positioning

`README.md`

- Omnigent is already positioned as an open-source meta-harness over multiple AI coding agents.
- It already promises sessions that sync across terminal, browser, phone, and desktop.
- It already supports cloud sandboxes and managed hosts.
- It already exposes policy/governance concepts.

MVP implication: do not add a separate product. Add a remote/local runner mode under the existing Omnigent architecture.

### Dependencies and packaging

`pyproject.toml`

Relevant existing dependencies and extras:

- `fastapi`, `starlette`, `uvicorn[standard]` for server and runner ASGI apps.
- `websockets` for tunnel/stream transport.
- `pexpect` and `pyte` for POSIX terminal stack.
- `mcp` for tool/server integration.
- optional sandbox extras: `modal`, `daytona`, `boxlite`, `cwsandbox`, `e2b`, `openshell`, `kubernetes`.
- native harness extras: `antigravity`, `copilot`, `cursor`.

MVP implication: the first pass should not add a new dependency unless a specific missing primitive is proven. Existing WebSocket, tmux, terminal, runner, and policy machinery should be reused.

## Server modules

### `omnigent/server/app.py`

Current responsibilities:

- Builds the FastAPI app.
- Creates `TunnelRegistry`, `RunnerRouter`, `HostRegistry`, `RunnerExitReports`, and `ServerMcpPool`.
- Starts `HarnessProcessManager` during app lifespan.
- Calls `set_runner_router(...)` and `set_runner_ws_factory(...)`.
- Seeds built-in native terminal agents.
- Wires routers for sessions, runner tunnel, terminal attach, policies, harnesses, MCP servers, comments, and default policies.
- Tracks host/session liveness through `runner_online`, `host_online`, and `host_version`.

MVP changes likely needed:

- Add a feature flag/capability in `/v1/info` for remote-local runner mode.
- Ensure session creation/update APIs can represent a chosen local runner and workspace.
- Extend host/runner liveness reporting so the UI can show: remote server online, local runner online, terminal running, terminal attach mode, workspace bound.
- Avoid putting file/shell execution in the server; server should route to runner.

### `omnigent/server/routes/runner_tunnel.py`

Expected role:

- Owns `WS /v1/runners/{runner_id}/tunnel`.
- Registers/deregisters runner tunnels.
- Receives runner hello frames.
- Should remain the canonical connection point for remote/local runner mode.

MVP changes likely needed:

- Add or verify runner hello fields: runner mode, OS, workspace roots, supported terminal transports, supported local tool capabilities.
- Enforce owner/admin binding on runner registration in auth-enabled deployments.
- Add validation for capability mismatch errors that are user-readable in the UI.

### `omnigent/server/routes/sessions.py`

Expected role:

- Owns session create/read/update/event APIs.
- Binds sessions to runners/hosts/workspaces.
- Starts or relaunches runner-backed sessions.

MVP changes likely needed:

- Add a first-class session creation flow for `execution_mode: local_runner` or equivalent.
- Store selected runner id and workspace path/handle in the conversation/session row or labels.
- Add a clean server-side path for creating a native terminal session bound to an existing local runner.
- Handle disconnected runner states with useful conflict responses rather than generic failures.

### `omnigent/server/routes/terminal_attach.py`

Current responsibilities:

- Exposes `WS /v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach`.
- Proxies attach to the runner when `runner_ws_factory` is configured.
- Falls back to local in-process terminal registry when there is no runner factory.
- Supports `read_only=true`.
- Supports `transport=control|pty`.
- Requires owner access for interactive write attach and read access for view-only attach when permissions are enabled.

MVP changes likely needed:

- Treat this as the main terminal mirroring path; do not create a new terminal WebSocket endpoint.
- Add UI-visible errors for runner unavailable, terminal missing, and transport unsupported.
- Add tests that remote-local attach works through the tunnel, not only in-process.
- Add explicit acceptance tests for read-only vs interactive attach permissions.

## Runner modules

### `omnigent/runner/app.py`

Current responsibilities:

- Runner FastAPI app.
- Owns harness subprocesses.
- Resolves harness type and spawn environment from agent specs.
- Owns session resources and runner-local terminal routes.
- Imports terminal bridges: `bridge_tmux_pty_to_websocket` and `bridge_tmux_control_to_websocket`.
- Auto-creates native terminals for multiple harnesses.
- Publishes terminal/resource/session events back to server.

MVP changes likely needed:

- Add a runner mode for user-installed local daemon that registers persistent workspace roots.
- Expose workspace list/validate endpoints, e.g. `GET /v1/runner/workspaces`, `POST /v1/runner/workspaces/validate`.
- Ensure native harness terminal launch uses the selected local workspace, not a temp per-session workspace, when the session is bound to local runner mode.
- Add clearer startup checks for `tmux`, native harness CLIs, shell, git, and OS constraints.
- Make errors client-safe but diagnostic enough for product UI.

### `omnigent/runner/routing.py`

Current responsibilities:

- Selects a live runner based on conversation runner binding.
- Builds an `httpx.AsyncClient` backed by `WSTunnelTransport`.
- Validates that a runner supports the requested harness.

MVP changes likely needed:

- Extend harness validation to include workspace/tool/terminal capability validation.
- Add helper methods for workspace/resource access where a session is runner-bound but not yet terminal-bound.
- Add tests for conflict cases: runner offline, runner lacks harness, runner lacks local workspace capability, runner belongs to another owner.

### `omnigent/runner/transports/ws_tunnel/frames.py`

Current responsibilities:

- Defines text JSON WebSocket tunnel frames.
- Supports request/response frames and WebSocket channel frames.
- `HelloFrame` advertises runner version, frame protocol version, harnesses, and envs.

MVP changes likely needed:

- Add protocol-versioned capability extension fields without breaking older servers/runners.
- Candidate fields: `mode`, `os`, `workspace_roots`, `terminal_transports`, `tool_capabilities`, `max_frame_size`, `supports_reconnect_resume`.
- Keep backwards compatibility: unknown hello fields should be ignored by older versions.

### `omnigent/runner/transports/ws_tunnel/registry.py`

Current responsibilities:

- Server-side registry of live runner WebSocket tunnels.
- Tracks runner sessions, owner, hello frame, outbound queue, in-flight requests, and WS channels.
- Newest connection wins for same runner id.
- Supports per-runner waiters for connect.

MVP changes likely needed:

- Persist or expose capability metadata from hello in UI/API responses.
- Ensure reconnect semantics preserve session affinity where safe.
- Add logs/metrics for tunnel churn, stale runners, replaced runners, and long-running WS channels.

### `omnigent/runner/resource_registry.py`

Current responsibilities:

- Runner-side authoritative facade for session-scoped resources.
- Owns primary OS environments and terminal resources.
- Supports terminal roles and lifecycles.
- Computes workspaces from runner environment variables and session ids.

MVP changes likely needed:

- Add explicit local workspace binding model instead of relying only on `OMNIGENT_RUNNER_WORKSPACE` or temp workspace roots.
- Add path validation and canonicalization for user-selected roots.
- Add resource metadata that tells UI whether a terminal/file/shell resource is local-runner-backed or cloud-runner-backed.

## Terminal modules

### `omnigent/terminals/registry.py`

Current responsibilities:

- Single tmux-based terminal abstraction.
- Keys terminals by `(conversation_id, terminal_name, session_key)`.
- Uses `inner.terminal.TerminalInstance`.
- Supports multiple terminal sessions per conversation.

MVP changes likely needed:

- Keep this as the source of truth for terminal lifetime.
- Add or verify API metadata for exact transport, cwd, command, lifecycle, and local/cloud execution location.
- Add terminal reconnect tests for required native terminal roles.

### `omnigent/terminals/ws_bridge.py`

Current responsibilities:

- PTY-to-WebSocket bridge for `tmux attach`.
- Streams raw terminal bytes to browser as binary frames.
- Sends browser binary input directly to PTY.
- Applies resize messages.
- Supports read-only mode.

MVP changes likely needed:

- Treat as fallback/high-parity mode for rendered tmux UI.
- Add regression tests for resize, binary input, mouse sequences, alternate screen, EOF handling, and read-only attach.

### `omnigent/terminals/control_bridge.py`

Current responsibilities:

- Uses `tmux -C` control mode.
- Streams raw pane bytes from `%output` to browser xterm.js.
- Seeds browser with `capture-pane -e -p`.
- Preserves browser-owned grid, scrollback, selection, and copy behavior.
- Uses hex `send-keys -H` for byte-exact input.

MVP changes likely needed:

- Prefer this for MVP terminal mirroring where possible.
- Add UI setting or server default for `transport=control`, with fallback to `pty`.
- Add explicit acceptance cases for cursor position, alternate screen, scrollback, text selection, paste, Ctrl/Alt sequences, and UTF-8 input.

## Tools, policies, permissions

### `omnigent/tools/local.py`

Current responsibilities:

- Loads and executes local Python tools in subprocesses.
- Supports sandbox tiers and dependency runners.
- Strips runner auth secrets before spawning tool subprocesses.

MVP changes likely needed:

- Do not treat arbitrary local tool dispatch as free shell access.
- Add local-runner tool guardrails before file write/shell execution.
- Make every local action auditable: command, cwd, status, duration, diff summary, approval id.

### `omnigent/stores/permission_store/*`

Expected role:

- Stores session-level access grants.
- Already integrated into terminal attach permissions.

MVP changes likely needed:

- Use this for runner/workspace access boundaries if possible.
- Add explicit permission levels for local runner drive/write/execute if current owner/read levels are not expressive enough.

### `omnigent/policies/*`

Expected role:

- Policy engine and built-in governance.
- Existing agent policies can pause for approval before risky actions.

MVP changes likely needed:

- Add built-in policy templates for local runner mode:
  - manual: ask for every write/shell command
  - assisted: allow read/list/search, ask for write/execute
  - auto: allow within workspace, ask/block risky commands
- Keep policy decisions centralized and visible in session history.

## Web and desktop UI areas

### `web/src/*`

Expected role:

- React/TypeScript SPA.
- Session sidebar, chat composer, terminal views, files/diffs, approval cards.

MVP changes likely needed:

- Add runner connection status UI.
- Add local workspace picker.
- Add session create flow for local runner execution.
- Add terminal transport indicator and reconnect status.
- Add diff/command approval cards for local runner actions.

### `web/electron/*`

Expected role:

- Native desktop wrapper around web UI.

MVP changes likely needed:

- Later: runner install/start helper, tray/status, deep link to pair local runner with server.
- Not required for first backend MVP if web pairing is enough.

## Tests to inspect or extend

Likely test areas:

- `tests/runner/*` — runner tunnel, terminal resource, harness launch, waiting status compatibility.
- `tests/server/integration/*` — app wiring, session creation, auth/permission behavior.
- `tests/e2e_ui/*` — terminal attach UX, idle notifications, collaboration, visual snapshots.
- `tests/tools/*` — local tool execution and sandbox behavior.
- `tests/host/*` — local host/runner daemon lifecycle.

## Proposed new design/task docs beyond this branch

When implementation starts, create or update:

- `designs/REMOTE_LOCAL_RUNNER.md`
- `designs/LOCAL_RUNNER_PERMISSIONS.md`
- `designs/TERMINAL_MIRRORING_ACCEPTANCE.md`
- `docs/remote-local-runner.md`

Those should be implementation docs, while this directory remains the planning map.
