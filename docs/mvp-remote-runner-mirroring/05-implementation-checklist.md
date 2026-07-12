# 05 — Implementation Checklist

This checklist is the reviewed status source for `feat/mvp-remaining-tracks`.
A checkmark means the production path is wired and the named acceptance evidence
exists. Helper-only code, sketches, or unit tests without a production caller do not
close an item.

## Status legend

- `[x]` complete and evidence-backed.
- `[ ]` open.
- `Partial` means useful implementation exists, but the end-to-end contract or stated
  guarantee is not complete.

## P0 — Branch and review setup

- [x] Add overview, codebase map, backend plan, UI plan, security plan, diagrams, and
  implementation checklist.
- [x] Correct the branch description from planning-only to implementation-in-progress.
- [ ] Open a draft PR from `feat/mvp-remaining-tracks` to `main`.
- [ ] Attach CI results and a reviewer-oriented change summary to the PR.

## P1 — Design records

- [ ] Add `designs/REMOTE_LOCAL_RUNNER.md` with the canonical discovery/create API.
- [ ] Add `designs/LOCAL_RUNNER_PERMISSIONS.md` with the selected shell security mode,
  audit schema, approval ownership, and single-/multi-replica support statement.
- [ ] Add `designs/TERMINAL_MIRRORING_ACCEPTANCE.md` with real byte/lifecycle criteria.
- [ ] Add API examples for runner discovery, workspace selection, session creation,
  local actions, and approval events.
- [ ] Record the persistence decision: `runner_id` on the conversation row plus opaque
  workspace/policy labels; no raw local path for local-runner mode.

P1 may be drafted during T10, but it is final only after T10 contracts stop changing.

## P2 — Runner capability protocol

- [x] Extend `HelloFrame` with optional capability fields.
- [x] Encode/decode optional fields leniently.
- [x] Retain capability metadata in the tunnel session.
- [x] Add old/new compatibility tests.
- [ ] Expose a canonical owner-scoped runner discovery response containing
  `runner_id`, online state, harnesses, terminal transports, and opaque workspaces.

The final row moved to T10 step 01 because the current web API remains hosts-shaped.

## P3 — Local runner CLI and pairing

- [x] Extend the existing `omnigent host` flow rather than add a second daemon model.
- [x] Persist daemon identity/pairing state in the existing config pattern.
- [x] Add status and stop/disconnect flows.
- [x] Add workspace add/remove persistence.
- [ ] Show one unified readiness view for tmux, shell, git, Node, and each advertised
  harness CLI.

Current evidence probes tmux/git/node and separately advertises configured harnesses;
shell and a unified readiness contract remain open.

## P4 — Workspace registry

- [x] Add the runner-side approved-workspace model.
- [x] Derive stable opaque workspace IDs.
- [x] Canonicalize roots and reject unknown IDs, absolute operation paths, traversal,
  and symlink escapes.
- [x] Seed the registry from host-approved environment state.
- [ ] Return bounded project metadata required by the UI: git status summary, shells,
  harness readiness, and missing/degraded state.

## P5 — Canonical session binding

- [x] Define execution-mode and workspace label keys.
- [x] Implement helper-level ownership, workspace, and harness validation.
- [ ] Add owner-scoped runner discovery to the public server API.
- [ ] Accept `runner_id + workspace_id` on public session creation.
- [ ] Reject `runner_id` combined with raw `workspace` or `host_id`.
- [ ] Call `validate_local_runner_binding` before conversation creation.
- [ ] Persist `runner_id` on the conversation and opaque workspace/policy labels.
- [ ] Expose the binding in the session snapshot.
- [ ] Preserve the binding across child/fork/resume/reconnect paths.
- [ ] Add route-level integration tests for owner, foreign runner, unknown workspace,
  unsupported harness, feature flag, and inheritance.

Tracked sequentially in `tasks/T10-canonical-contract/step-01-canonical-session-binding.md`.
The existing helper tests do not close these route items.

## P6 — Native terminal launch in the selected workspace

- [x] Existing host/raw-path launch can start native terminals in the selected host
  directory.
- [x] Codex-native and at least one additional native harness have workspace launch
  coverage.
- [x] Terminal resources publish and attach through the runner tunnel.
- [x] Unsupported/degraded terminal status is surfaced.
- [ ] Revalidate all launch/reconnect paths using the canonical `workspace_id` binding
  after T10 step 01.

## P7 — Local actions gateway

- [x] Inventory existing file/shell execution paths.
- [x] Add a runner-local action gateway.
- [x] Implement workspace-contained `read_file`, `list_dir`, and `write_file`.
- [x] Add write diff preview and stale-content conflict detection.
- [x] Bound shell duration and captured output; strip runner auth from the child env.
- [ ] Freeze the shell security contract and implement the stated boundary.
- [x] Keep `search_files` off the gateway capability contract until it has
  the gateway audit/policy path; it remains an explicit filesystem route.
- [x] Keep `git_status` and `git_diff` off the gateway capability contract
  until they converge on a fixed-argv, authorized read-only path.
- [ ] Implement `apply_patch` with preview and race-safe write semantics before
  advertising it.
- [ ] Add request-size limits and re-resolve/no-follow protections for writes.

Approval alone does not contain an arbitrary shell command. T10 steps 02 and 04 own
these blockers.

## P8 — Permission, policy, and audit integration

- [x] Add manual, assisted, and auto policy values with fail-closed fallback.
- [x] Ask-gate side-effectful actions in manual mode.
- [x] Enforce owner-only local-action approval in the server route for a single
  process.
- [x] Enforce read-only versus interactive terminal attach permissions before proxy.
- [x] Publish local-action lifecycle events and persist terminal outcomes by
  `action_id`.
- [ ] Match preset descriptions to actual shell behavior after T10 step 02.
- [ ] Make persisted audit data allowlisted, bounded, and secret-safe by value, not
  merely by exact key removal.
- [ ] Prove logs/history omit bearer tokens, auth headers, full commands, file
  contents, output, and absolute home paths.
- [ ] State single-replica approval support for alpha or move pending approval
  ownership to a shared store.

`tests/server/test_local_action_persistence.py` proves persistence mechanics, not the
full payload-free guarantee.

## P9 — Runner UX

- [x] Add the feature capability probe and runner status presentation.
- [x] Add terminal transport/reconnect state and offline recovery copy.
- [ ] Build the runner/workspace picker against the canonical owner-scoped discovery
  model from T10 step 01.
- [ ] Send `runner_id + workspace_id + local_runner_policy`, never a path-label
  round-trip.
- [ ] Show harness/workspace incompatibility and degraded readiness.
- [ ] Complete the capability dashboard with truthful T10 step 04 data.

Tracked in `tasks/T09-runner-ux/`; blocked by T10 steps 01 and 04.

## P10 — Terminal parity and reconnect acceptance

Existing unit/route coverage:

- [x] Control/PTY close-code mapping and fallback behavior.
- [x] Read-only and non-owner interactive attach authorization.
- [x] UI lifecycle state for runner offline/reconnected, terminal detached/exited,
  retry, and refresh recovery.

Real end-to-end coverage still open:

- [ ] Build a real server + runner + tmux + browser fixture.
- [ ] Test resize propagation.
- [ ] Test multiline/large paste and UTF-8.
- [ ] Test Ctrl-C, ESC, arrows, tab, and alternate-screen transitions.
- [ ] Test disconnect/reconnect during active output and after browser refresh.
- [ ] Distinguish runner offline, terminal exited, transport unsupported, and
  permission denial at the live WebSocket boundary.

Tracked in `tasks/T12-terminal-parity-e2e.md`.

## P11 — Observability

- [x] Emit `omnigent.local_action.total` with bounded kind/status/policy labels.
- [x] Emit `omnigent.approval.decision_total` with bounded decision labels.
- [ ] Add structured runner connect/disconnect/reconnect logs.
- [ ] Add terminal attach transport and close-code metrics.
- [ ] Add workspace validation and capability mismatch metrics.
- [ ] Add a diagnostics endpoint or admin projection for live runner capabilities.
- [ ] Add log-capture tests enforcing the T10 audit/log secrecy rules.

## P12 — Documentation and rollout

- [x] Feature flag is off by default and surfaced as top-level
  `remote_local_runner` in `/v1/info`.
- [ ] Add user pairing and workspace-selection documentation.
- [ ] Add admin enable/disable, single-replica limitation, and recovery documentation.
- [ ] Add security documentation for policy modes, shell mode, approvals, audit data,
  and retention.
- [ ] Add troubleshooting for runner offline, tmux/sandbox missing, harness missing,
  capability mismatch, and reconnect.
- [ ] Add a manual QA script covering two users, denial, reconnect, and secret checks.
- [ ] Map dev/alpha/beta gates to named CI jobs and branch protection.
- [ ] Add release notes only after the alpha gate is green.

## Remaining dependency order

### Stage 1 — sequential blockers

1. **T10-01:** canonical owner-scoped runner discovery and `runner_id + workspace_id`
   session binding.
2. **T10-02:** shell security decision and implementation/documentation.
3. **T10-03:** allowlisted audit schema, value redaction, limits, and race hardening.
4. **T10-04:** capability truthfulness and gateway convergence.

### Stage 2 — parallel after Stage 1

- **T09:** runner/workspace picker and capability dashboard.
- **T11:** approval cards, write diff presentation, and approval-flow E2E.
- **T12:** real terminal parity and reconnect E2E.

Each track is sequential internally, but the three tracks can run in parallel.

### Stage 3 — release preparation

1. Complete P11 observability.
2. Finalize P1 design records from the implemented contracts.
3. Complete P12 docs, manual QA, CI jobs, and rollout gates.
4. Open/update the draft PR with evidence links.

## Recommended remaining PRs

1. `feat(sessions): add canonical local-runner discovery and binding`
2. `feat(runner): freeze shell and audit security contracts`
3. `feat(runner): converge local read capabilities`
4. Parallel runner UX, approval UI, and terminal E2E PRs
5. Observability and release-documentation PR
