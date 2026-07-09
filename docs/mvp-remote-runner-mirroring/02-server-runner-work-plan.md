# 02 — Server and Runner Work Plan

This file turns the research into concrete backend tasks. It does not change code.

## Implementation principle

Use the existing runner tunnel and session resource model. The server should coordinate, authorize, persist, and route. The runner should own local execution, local terminals, local files, local shell commands, and OS-specific behavior.

## Phase 0 — Product boundary and naming

### Task 0.1 — Define the feature name

Candidate names:

- Remote/Local Runner
- Local Workspace Runner
- Remote Agent + Local Workspace
- Split Execution Mode

Recommended internal name: `remote_local_runner`.

Acceptance criteria:

- Feature name appears consistently in docs, flags, API models, UI labels, telemetry names, and tests.
- Docs describe legitimate self-hosted remote development, workspace mobility, and local compute reuse.
- Docs do not position the feature as provider-policy or regional-restriction evasion.

### Task 0.2 — Add an implementation design doc

Target file:

- `designs/REMOTE_LOCAL_RUNNER.md`

Content to include:

- System diagram.
- Session lifecycle.
- Runner pairing flow.
- Workspace selection.
- Terminal attach flow.
- Local tool dispatch flow.
- Permission and policy gates.
- Failure/reconnect behavior.

## Phase 1 — Runner pairing and capability discovery

### Task 1.1 — Extend runner hello capabilities

Target files:

- `omnigent/runner/transports/ws_tunnel/frames.py`
- `omnigent/runner/transports/ws_tunnel/registry.py`
- `omnigent/server/routes/runner_tunnel.py`
- tests under `tests/runner/` and `tests/server/`

Current basis:

- `HelloFrame` already includes `runner_version`, `frame_protocol_version`, `harnesses`, and `envs`.

Add planning-level fields:

```python
mode: Literal["local", "managed", "in_process"] | None
os: str | None
arch: str | None
workspace_capabilities: dict[str, Any]
terminal_transports: list["control", "pty"]
tool_capabilities: list[str]
reconnect: dict[str, Any]
```

Implementation notes:

- Preserve backwards compatibility by making new fields optional.
- Older servers should ignore unknown fields.
- New servers should tolerate older runners that do not advertise these fields.
- Never advertise raw secret paths, tokens, or key locations.

Acceptance criteria:

- Server can show runner capabilities in a diagnostic endpoint.
- Session binding can reject unsupported runner/harness/workspace combinations with structured error codes.
- Unit tests cover old-runner/new-server and new-runner/old-server compatibility.

### Task 1.2 — Add runner pairing/status endpoint if missing

Target files:

- `omnigent/server/routes/hosts.py` or runner-related route module
- `omnigent/server/app.py`
- `omnigent/stores/host_store/*`
- `web/src/*` later for status display

Desired endpoints:

- `GET /v1/runners` or `GET /v1/hosts` extension: list online runners owned by caller.
- `GET /v1/runners/{runner_id}`: runner status, capabilities, last seen, version, owner, workspace mode.
- `POST /v1/runners/{runner_id}/ping` or reuse existing health/liveness if already present.

Acceptance criteria:

- Auth-enabled server only lists caller-owned runners unless caller is admin.
- No-auth local dev preserves simple single-user behavior.
- Runner version and capability mismatches are visible to UI.

### Task 1.3 — Add CLI command for connecting a local runner to a remote server

Target files:

- `omnigent/cli.py`
- `omnigent/runner/_entry.py`
- `omnigent/host/local_server.py`
- tests under `tests/cli/` and `tests/host/`

Suggested command shapes:

```bash
omni runner connect --server https://example.com --workspace ~/project
omni runner status
omni runner disconnect
```

or, if the current CLI already has a host/connect command, extend that instead of adding a new top-level group.

Acceptance criteria:

- Local runner can connect to a remote server with a stable runner id.
- Runner id and pairing token are stored under `~/.omnigent` or equivalent existing state location.
- CLI shows server URL, runner id, online/offline, workspace roots, supported harnesses, tmux availability.
- Runner exits cleanly and deregisters when stopped.

## Phase 2 — Workspace advertisement and selection

### Task 2.1 — Model user-approved local workspace roots

Target files:

- `omnigent/runner/resource_registry.py`
- `omnigent/runner/app.py`
- `omnigent/inner/datamodel.py` if a typed model is needed
- `omnigent/entities/session_resources.py` if exposed as a resource
- tests under `tests/runner/`

Requirements:

- A local runner can expose one or more workspace roots.
- Workspace paths must be canonicalized with `Path(...).expanduser().resolve()`.
- Symlink escapes must be considered explicitly.
- The runner should expose stable workspace ids/handles to the server/UI rather than requiring the UI to persist raw host paths everywhere.
- The server may display a path label, but path enforcement must happen on the runner.

Suggested model:

```json
{
  "workspace_id": "ws_...",
  "display_name": "omnigent",
  "root": "/Users/alice/projects/omnigent",
  "capabilities": ["read", "write", "shell", "git", "terminal"],
  "policy_mode": "manual|assisted|auto"
}
```

Acceptance criteria:

- Runner refuses file/shell actions outside selected workspace.
- Runner can list configured workspaces.
- Session can be bound to one workspace id.
- UI can show workspace name/path and runner online state.

### Task 2.2 — Persist session workspace binding

Target files:

- `omnigent/server/routes/sessions.py`
- `omnigent/stores/conversation_store/*`
- DB models/migrations if the current schema lacks fields
- `omnigent/entities/*` session response models
- tests under `tests/server/integration/`

Options:

1. Add columns to conversation/session table: `runner_id`, `host_id`, `workspace_id`, `workspace_label`, `execution_mode`.
2. If `runner_id`/`host_id` already exist, add only workspace/execution fields.
3. If schema churn is risky, use session labels for MVP, then migrate to columns later.

Acceptance criteria:

- A session snapshot includes its runner/workspace binding.
- Fork/resume behavior preserves or intentionally clears workspace binding with explicit rules.
- Session creation fails with a readable error if workspace is missing or runner is offline.

### Task 2.3 — Add workspace validation endpoint on runner

Target files:

- `omnigent/runner/app.py`
- `omnigent/runner/resource_registry.py`
- tests under `tests/runner/`

Desired behavior:

- Validate `workspace_id` or path handle before session bind.
- Return project metadata: git root, dirty status, package manager hints, available shells, tmux availability.
- Do not traverse the entire repo on every validation; keep it bounded.

Acceptance criteria:

- Invalid workspace returns structured 4xx error.
- Workspace metadata does not leak secrets.
- Slow filesystems are protected by timeout.

## Phase 3 — Session creation and harness launch

### Task 3.1 — Add local-runner session create flow

Target files:

- `omnigent/server/routes/sessions.py`
- `omnigent/runner/routing.py`
- `omnigent/runner/app.py`
- `omnigent/runtime/harnesses/process_manager.py`
- tests under `tests/server/integration/` and `tests/runner/`

Desired flow:

1. UI requests new session with selected agent/harness, runner id, and workspace id.
2. Server validates caller can use runner.
3. Server stores session binding.
4. Server asks runner to create or prepare resources.
5. Runner launches required terminal/harness with cwd set to selected workspace.
6. Server returns session id and initial resources.

Acceptance criteria:

- Native terminal sessions start in the selected workspace.
- Harness capability mismatch returns a user-readable conflict.
- Terminal resource appears in session resources and can attach through existing endpoint.

### Task 3.2 — Align native harness auto-create functions with selected workspace

Target files:

- `omnigent/runner/app.py`
- native bridge helpers such as `*_native_bridge.py`, `*_native_forwarder.py`, `*_native_permissions.py`
- tests for codex/claude/cursor/opencode/pi/goose/hermes as relevant

Current basis:

- Existing functions auto-create native terminals and mirror forwarders.
- Workspace is often resolved from session snapshot or `OMNIGENT_RUNNER_WORKSPACE`.

MVP changes:

- Make workspace source explicit: session workspace binding wins.
- Add logs showing selected workspace id/path label, not only raw cwd.
- Ensure forwarders and approval mirrors use the same session id and workspace root.

Acceptance criteria:

- Codex and one other native harness work end-to-end first.
- Other harnesses either work or return clean unsupported status for MVP.

## Phase 4 — Local file/shell/tool dispatch

### Task 4.1 — Inventory current local tools and OS tools

Target files to inspect during implementation:

- `omnigent/tools/local.py`
- `omnigent/tools/builtins/*`
- `omnigent/runtime/workflow.py`
- `omnigent/runtime/caps.py`
- `omnigent/inner/os_env.py`
- `omnigent/inner/datamodel.py`

Questions to answer before code changes:

- Which current tools read files?
- Which current tools write files?
- Which tools run shell commands?
- Which tools already use the runner resource registry?
- Which tools run in server process vs runner process?
- Where are tool calls policy-evaluated?

Acceptance criteria for inventory PR:

- A table of tool names, side effects, execution location, permission phase, and MVP handling.
- No local destructive action enabled without a policy/permission path.

### Task 4.2 — Add runner-side local action gateway

Target files:

- `omnigent/runner/app.py`
- new module candidate: `omnigent/runner/local_actions.py`
- new module candidate: `omnigent/runner/workspace_policy.py`
- tests under `tests/runner/test_local_actions.py`

Desired primitive actions:

- `read_file`
- `write_file`
- `list_dir`
- `search_files`
- `apply_patch`
- `run_shell`
- `git_status`
- `git_diff`

Rules:

- Every path must resolve inside the bound workspace.
- Every write should generate a diff summary before/after where possible.
- Every shell command should record command, cwd, env allowlist, duration, exit code, stdout/stderr size.
- Dangerous commands are blocked or ask-gated depending on mode.

Acceptance criteria:

- Unit tests for path traversal, symlink escape, absolute path escape, shell cwd escape.
- Large output truncation is deterministic and safe.
- Secrets in runner auth env vars are stripped before subprocess execution.

### Task 4.3 — Route tool calls to the local runner

Target files:

- `omnigent/runtime/workflow.py`
- `omnigent/runner/routing.py`
- `omnigent/tools/base.py`
- `omnigent/tools/local.py`
- policy evaluation modules

Desired behavior:

- For local-runner sessions, tools with local side effects execute on the bound runner.
- Server does not perform workspace file/shell work directly.
- Tool responses stream back to the agent/session normally.

Acceptance criteria:

- A local-runner session can read, write, apply patch, run tests, and return output.
- Policy ask gates work before side-effectful actions.
- Concurrent tool calls do not corrupt workspace state.

## Phase 5 — Reconnect and lifecycle

### Task 5.1 — Preserve session binding through runner reconnect

Target files:

- `omnigent/runner/transports/ws_tunnel/registry.py`
- `omnigent/runner/routing.py`
- `omnigent/server/routes/sessions.py`
- `omnigent/stores/conversation_store/*`

Desired behavior:

- Runner reconnects with same runner id.
- Server updates live registry but keeps session affinity.
- Terminal attach returns a clean reconnecting/offline state while runner is absent.
- When runner returns, existing terminal resources are either reattached if alive or recreated if lifecycle says required.

Acceptance criteria:

- Tests simulate tunnel disconnect/reconnect.
- UI can distinguish runner offline vs terminal exited vs session stopped.

### Task 5.2 — Graceful stop and cleanup

Target files:

- `omnigent/runner/app.py`
- `omnigent/runner/resource_registry.py`
- `omnigent/terminals/registry.py`
- `omnigent/host/local_server.py`
- CLI stop/status commands

Acceptance criteria:

- Stopping the runner cleans up subprocesses it owns.
- Server reflects offline state promptly.
- No orphaned tmux sessions remain for required agent terminals unless explicitly configured to preserve them.

## Phase 6 — API and compatibility contracts

### Task 6.1 — Define API models

Target areas:

- Session create request/response models.
- Runner info response model.
- Workspace info response model.
- Local action approval/event model.

Acceptance criteria:

- Models are documented in design doc.
- Server and runner versions can be mixed safely within one minor release window.
- Old clients degrade gracefully.

### Task 6.2 — Add structured errors

Error codes to consider:

- `runner_unavailable`
- `runner_capability_mismatch`
- `workspace_not_found`
- `workspace_outside_allowed_roots`
- `terminal_transport_unsupported`
- `local_action_requires_approval`
- `local_action_blocked_by_policy`
- `terminal_reconnect_required`

Acceptance criteria:

- UI can render each as a specific recovery action.
- Tests assert error code, not only status code.
