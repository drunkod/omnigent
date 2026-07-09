# 05 — Implementation Checklist

This is the execution checklist derived from the research and codebase review. It is planning only.

## High-level finding

The codebase already contains most of the infrastructure needed for the MVP:

- Server/runner split.
- Persistent runner WebSocket tunnel.
- Conversation-to-runner routing.
- Host/runner liveness concepts.
- Runner-owned harness subprocesses.
- Runner-owned session resources.
- tmux terminal registry.
- PTY and control-mode WebSocket terminal bridges.
- Native terminal agent launchers.
- Policy/approval primitives.
- Permission store and owner/read attach model.

The missing work is primarily productization and hardening:

- Pairing a user's local runner to a remote server.
- Advertising/selecting local workspaces.
- Persisting workspace binding per session.
- Routing side-effectful local file/shell actions to the runner with approval gates.
- Exposing this as a coherent UI flow.
- Adding terminal parity and reconnect tests.

## P0 — Planning PR already represented by this branch

- [x] Create planning branch.
- [x] Add MVP overview.
- [x] Map existing codebase modules.
- [x] Add backend/server/runner task plan.
- [x] Add terminal/UI task plan.
- [x] Add permissions/security/test plan.
- [x] Add implementation checklist.
- [ ] Open PR from `planning/mvp-remote-runner-mirroring` to `main` for review.

## P1 — Design docs

- [ ] Add `designs/REMOTE_LOCAL_RUNNER.md`.
- [ ] Add `designs/LOCAL_RUNNER_PERMISSIONS.md`.
- [ ] Add `designs/TERMINAL_MIRRORING_ACCEPTANCE.md`.
- [ ] Add API model examples for runner, workspace, session creation, local actions.
- [ ] Add migration decision: labels vs DB columns for workspace binding.

## P2 — Runner capability protocol

- [ ] Extend `HelloFrame` with optional capability fields.
- [ ] Update frame encode/decode tests.
- [ ] Update tunnel registry to retain capability metadata.
- [ ] Update runner tunnel route to expose capability errors.
- [ ] Add compatibility tests for old/new runner/server combinations.

Target files:

- `omnigent/runner/transports/ws_tunnel/frames.py`
- `omnigent/runner/transports/ws_tunnel/registry.py`
- `omnigent/server/routes/runner_tunnel.py`
- `tests/runner/test_ws_tunnel_*`

## P3 — Local runner CLI and pairing

- [ ] Decide whether to extend existing host/connect command or add `omni runner connect`.
- [ ] Store runner id and pairing auth in existing `~/.omnigent` state pattern.
- [ ] Add `omni runner status`.
- [ ] Add `omni runner disconnect` or equivalent stop flow.
- [ ] Show tmux, shell, git, Node, harness CLI readiness.

Target files:

- `omnigent/cli.py`
- `omnigent/host/local_server.py`
- `omnigent/runner/_entry.py`
- `tests/cli/*`
- `tests/host/*`

## P4 — Workspace registry

- [ ] Add runner-side approved workspace model.
- [ ] Add workspace list/validate endpoints.
- [ ] Canonicalize and enforce workspace paths.
- [ ] Add symlink escape tests.
- [ ] Return project metadata: git root/status, available shells, harness readiness.

Target files:

- `omnigent/runner/app.py`
- `omnigent/runner/resource_registry.py`
- new candidate: `omnigent/runner/workspaces.py`
- `tests/runner/test_workspaces.py`

## P5 — Session binding

- [ ] Add `execution_mode` concept if not already present.
- [ ] Persist selected `runner_id` and `workspace_id` or equivalent labels.
- [ ] Validate caller owns runner/workspace.
- [ ] Validate selected harness is supported by runner.
- [ ] Ensure session snapshot exposes binding to UI.
- [ ] Define fork/resume semantics.

Target files:

- `omnigent/server/routes/sessions.py`
- `omnigent/stores/conversation_store/*`
- `omnigent/entities/*`
- DB migrations if columns are added
- `tests/server/integration/test_remote_local_runner_sessions.py`

## P6 — Native terminal launch in selected workspace

- [ ] Make selected session workspace win over default temp workspace.
- [ ] Launch Codex-native in selected workspace.
- [ ] Launch one additional native terminal in selected workspace.
- [ ] Publish terminal resource event.
- [ ] Confirm terminal attach works through runner tunnel.
- [ ] Add fallback/unsupported status for other harnesses.

Target files:

- `omnigent/runner/app.py`
- `omnigent/runner/resource_registry.py`
- native modules such as `codex_native*`, `claude_native*`, `cursor_native*`
- `tests/runner/test_*native*`

## P7 — Local actions gateway

- [ ] Inventory all existing file/shell tools and their execution location.
- [ ] Add runner-local action gateway.
- [ ] Implement read/list/search.
- [ ] Implement write/apply-patch with diff preview.
- [ ] Implement shell command execution with cwd/env enforcement.
- [ ] Implement git status/diff helpers.
- [ ] Stream/truncate outputs safely.

Target files:

- new candidate: `omnigent/runner/local_actions.py`
- new candidate: `omnigent/runner/workspace_policy.py`
- `omnigent/tools/local.py`
- `omnigent/runtime/workflow.py`
- `tests/runner/test_local_actions.py`

## P8 — Permission and policy integration

- [ ] Add local runner policy presets: manual, assisted, auto.
- [ ] Ask-gate every side-effectful action in manual mode.
- [ ] Block workspace escapes in all modes.
- [ ] Add approval event model for local actions.
- [ ] Ensure approvals are owner-only for MVP.
- [ ] Add session history audit records.

Target files:

- `omnigent/policies/*`
- `omnigent/runner/pending_approvals.py`
- `omnigent/stores/permission_store/*`
- `omnigent/server/routes/terminal_attach.py`
- `tests/server/integration/test_remote_local_runner_permissions.py`

## P9 — UI flow

- [ ] Add runner status panel.
- [ ] Add workspace picker in new session flow.
- [ ] Add local/cloud execution mode indicator.
- [ ] Add terminal transport/reconnect status.
- [ ] Add approval card for local shell/write action.
- [ ] Add diff preview before write/apply-patch.
- [ ] Add offline/reconnect recovery copy.

Target files:

- `web/src/*`
- `web/electron/*` later for helper UX
- `tests/e2e_ui/*`

## P10 — Terminal parity and reconnect tests

- [ ] Test control-mode attach.
- [ ] Test PTY attach fallback.
- [ ] Test resize.
- [ ] Test paste.
- [ ] Test Ctrl-C and ESC sequences.
- [ ] Test read-only attach.
- [ ] Test non-owner denial for interactive attach.
- [ ] Test runner disconnect/reconnect.
- [ ] Test terminal exited vs runner offline state.

Target files:

- `tests/runner/test_terminal_attach_tunnel.py`
- `tests/e2e_ui/terminal/*`
- `tests/server/integration/*`

## P11 — Observability

- [ ] Add structured logs for runner connect/disconnect.
- [ ] Add metrics for local action decisions.
- [ ] Add metrics for terminal attach transport and close codes.
- [ ] Add diagnostics endpoint for runner capabilities.
- [ ] Ensure logs do not leak secrets or full file contents.

Target files:

- `omnigent/server/performance_metrics.py`
- `omnigent/runtime/telemetry.py`
- `omnigent/runner/*`

## P12 — Documentation and rollout

- [ ] Add user docs: pairing local runner with remote server.
- [ ] Add admin docs: enabling/disabling feature.
- [ ] Add security docs: permission modes and local action logs.
- [ ] Add troubleshooting docs: runner offline, tmux missing, harness missing.
- [ ] Add alpha feature flag.
- [ ] Add manual QA script to docs.

Target files:

- `docs/remote-local-runner.md`
- `README.md` short mention after beta, not immediately
- release notes when feature is behind flag

## Suggested first implementation PR after this planning branch

Title:

```text
feat(runner): advertise local runner capabilities and workspace roots
```

Scope:

- Extend runner hello capabilities with optional fields.
- Add runner capability model tests.
- Add workspace root config/validation in runner only.
- Do not touch UI yet.
- Do not enable shell/write actions yet.

Why this first:

It creates the data contract needed by server and UI without changing high-risk execution behavior.

## Suggested second implementation PR

Title:

```text
feat(sessions): create runner-bound sessions with workspace metadata
```

Scope:

- Add session binding to selected runner/workspace.
- Add validation via runner route.
- Add server integration tests.
- No local shell/write actions yet.

## Suggested third implementation PR

Title:

```text
feat(terminal): attach native terminal sessions through local runner workspace
```

Scope:

- Launch one native terminal in selected workspace.
- Attach via existing terminal resource WebSocket.
- Add terminal parity tests.

## Suggested fourth implementation PR

Title:

```text
feat(runner): add permissioned local action gateway
```

Scope:

- Read/list/search first.
- Then write/apply-patch/shell behind manual approval.
- Add security tests before UI automation.
