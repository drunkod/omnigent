# 04 — Permissions, Security, Tests, and Rollout Gates

This file defines the safety and validation work for the remote/local runner MVP. It is planning only.

## Security stance

The local runner can access the user's real filesystem and execute commands. Therefore the local runner must be treated as a privileged component and must be permissioned, observable, auditable, and bounded by workspace policy.

The MVP must not expose unrestricted shell access from the server to a local computer.

## Permission modes

### Manual mode

Default for first MVP.

Rules:

- Ask before every file write.
- Ask before every shell command.
- Allow low-risk reads inside the workspace.
- Block path traversal and workspace escapes.
- Show full diff/command preview before approval.

### Assisted mode

Good second mode after manual mode is stable.

Rules:

- Allow read/list/search inside workspace.
- Allow low-risk git status/diff commands.
- Ask before write/apply-patch/shell commands.
- Block known destructive commands unless explicitly overridden by owner.

### Auto mode

Do not enable by default in MVP.

Rules:

- Allow writes and shell commands only inside workspace.
- Ask for destructive/risky commands.
- Block workspace escapes, secret access, global installs, history rewrites, and system path modifications by default.

## Risk categories

### Always block unless explicitly configured

- Commands outside selected workspace.
- Access to SSH keys, cloud credentials, tokens, browser profiles, password stores, OS keychains.
- `rm -rf /`, root directory deletes, home directory deletes.
- `sudo`, privilege escalation, changing file ownership globally.
- Modifying shell profile files outside workspace.
- Modifying Git global config.
- Uploading arbitrary local files not under workspace.
- Running commands that open reverse shells or persistent background listeners without clear user action.

### Ask-gate by default

- File writes.
- Patch application.
- Shell execution.
- Package install commands.
- Test commands with scripts from package manifests.
- Git commits, resets, rebases, checkout of destructive paths.
- Removing files or directories inside workspace.

### Allow by default in manual/assisted if inside workspace

- Read file.
- List directory.
- Search files.
- Git status.
- Git diff.
- Read package metadata.

## Files/modules to use

### Terminal attach permissions

Target file:

- `omnigent/server/routes/terminal_attach.py`

Current behavior to preserve:

- Read-only attach requires read access when permissions are enabled.
- Interactive attach requires owner access.
- Raw terminal input is owner-only because keystrokes carry no per-user identity.

MVP task:

- Add tests proving local-runner terminal attach keeps the same permission behavior through the runner tunnel.

### Session permissions

Target files:

- `omnigent/stores/permission_store/*`
- `omnigent/server/routes/_auth_helpers.py`
- `omnigent/server/routes/sessions.py`

MVP tasks:

- Confirm session owner is the only identity allowed to bind a local runner workspace.
- Confirm non-owner cannot create an interactive terminal attach.
- Decide whether collaborator can approve local actions; recommended MVP: owner only.

### Tool policies

Target files:

- `omnigent/policies/*`
- `omnigent/policies/builtins/*`
- `omnigent/runtime/workflow.py`
- `omnigent/runner/pending_approvals.py`

MVP tasks:

- Add built-in local runner policy presets.
- Ensure all side-effectful runner actions emit policy evaluation context.
- Ensure approval responses are recorded in session history.

### Local execution

Target files:

- `omnigent/tools/local.py`
- `omnigent/runner/app.py`
- `omnigent/runner/local_actions.py` candidate
- `omnigent/runner/workspace_policy.py` candidate

MVP tasks:

- Keep auth secrets stripped from child process env.
- Add env allowlist for shell commands.
- Bound stdout/stderr returned to agent/UI.
- Record full logs locally for debugging, but avoid leaking secrets to server logs.

## Local action audit model

Every local action should produce an audit record with:

```json
{
  "action_id": "act_...",
  "session_id": "conv_...",
  "runner_id": "runner_...",
  "workspace_id": "ws_...",
  "kind": "read_file|write_file|apply_patch|run_shell|git_status|git_diff",
  "requested_by": "agent|user",
  "approval_id": "approval_...",
  "policy_mode": "manual|assisted|auto",
  "status": "requested|approved|denied|blocked|running|completed|failed",
  "cwd": "<workspace-relative cwd>",
  "path_summary": ["src/foo.py"],
  "command_summary": "pytest tests/foo",
  "risk_flags": ["shell", "writes_files"],
  "started_at": "...",
  "finished_at": "...",
  "exit_code": 0,
  "output_truncated": false
}
```

Rules:

- Prefer workspace-relative paths in server-visible events.
- Avoid sending absolute local home paths unless user explicitly reveals them in UI.
- Never include runner pairing tokens or auth headers.

## Test plan

### Unit tests

Add tests for:

- Workspace path canonicalization.
- Symlink escape blocking.
- `..` traversal blocking.
- Absolute path escape blocking.
- File read/write inside workspace.
- Patch applies only inside workspace.
- Shell cwd forced inside workspace.
- Dangerous command classification.
- Env secret stripping.
- Large stdout/stderr truncation.
- Runner capability parsing with old/new hello frames.

Likely files:

- `tests/runner/test_local_actions.py`
- `tests/runner/test_workspace_policy.py`
- `tests/runner/test_ws_tunnel_capabilities.py`
- `tests/server/test_runner_local_mode.py`

### Integration tests

Add tests for:

- Server creates session bound to runner/workspace.
- Server routes file/shell action to runner over `WSTunnelTransport`.
- Runner offline returns structured error.
- Runner lacks harness returns capability mismatch.
- Terminal attach through runner tunnel works.
- Read-only attach for collaborator works if permissions allow read.
- Interactive attach for collaborator is denied.
- Owner can approve local shell command.
- Denied action does not execute.

Likely files:

- `tests/server/integration/test_remote_local_runner_sessions.py`
- `tests/server/integration/test_remote_local_runner_permissions.py`
- `tests/runner/test_terminal_attach_tunnel.py`

### E2E UI tests

Add or extend Playwright tests for:

- New session local-runner mode.
- Workspace picker.
- Runner status indicator.
- Terminal attach/reconnect.
- Approval card for local write.
- Diff preview.
- Runner offline banner.

Likely files:

- `tests/e2e_ui/sessions/test_remote_local_runner.py`
- `tests/e2e_ui/terminal/test_terminal_attach_remote_runner.py`

### Manual QA

Before enabling outside dev builds:

1. Start remote server with auth enabled.
2. Login as user A.
3. Pair local runner as user A.
4. Create local-runner session against a test repo.
5. Confirm terminal starts in selected workspace.
6. Ask agent to read a file.
7. Ask agent to edit a file.
8. Confirm approval/diff appears.
9. Deny an action and verify no change.
10. Approve action and verify change.
11. Login as user B with shared read access.
12. Confirm user B can view read-only terminal if permitted.
13. Confirm user B cannot type into terminal.
14. Disconnect runner.
15. Confirm UI shows runner offline.
16. Reconnect runner.
17. Confirm session can continue.

## Telemetry and observability

Add metrics/logging for:

- Runner connect/disconnect count.
- Runner reconnect latency.
- Runner version/capability mismatch.
- Workspace validation failures.
- Terminal attach mode: control vs pty.
- Terminal attach close codes.
- Local action count by kind/status.
- Approval requested/approved/denied counts.
- Blocked dangerous command count.

Do not log:

- Full file contents.
- Full command output by default.
- Pairing tokens.
- Auth headers.
- Local absolute paths unless necessary and marked safe.

## Rollout gates

### Gate 1 — Dev-only

Required:

- Feature flag off by default.
- Manual mode only.
- One supported native harness.
- Local runner session create works.
- Terminal attach works.
- Unit tests pass.

### Gate 2 — Alpha

Required:

- Two supported native harnesses.
- Workspace picker UI.
- Approval cards.
- Diff preview.
- Runner offline/reconnect UI.
- Integration tests for tunnel, permissions, workspace escape blocking.

### Gate 3 — Beta

Required:

- Assisted mode.
- Better diagnostics.
- Installation/pairing docs.
- E2E UI coverage.
- Backwards compatibility tests for runner/server version skew.

## Open questions

1. Should workspace roots be configured only from CLI, or can UI request new roots that require local runner approval?
2. Should collaborator approvals ever be allowed, or owner-only for all local side effects?
3. Should local runner support multiple simultaneous sessions in the same workspace?
4. Should each session create a git worktree for isolation by default?
5. How should the product handle native harnesses that manage their own permission prompts?
6. Should command classification live in policies, runner workspace policy, or both?
7. What is the minimum supported OS for local runner mode?
8. Should Windows local runner support SDK-only mode while disabling native tmux terminal wrappers?
9. What exact UI state should be shown when runner is online but terminal process exited?
10. Should cloud-execution mode reuse the same APIs with `execution_mode: managed_host`?
