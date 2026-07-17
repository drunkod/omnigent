# 05 — Implementation Checklist

Status reviewed on 2026-07-17 against the active stacked pull requests:

- PR #2, `feat/mvp-runner-binding-approvals` at `2dbe4b85` before this status refresh;
- PR #3, `feat/mvp-terminal-mirroring`, whose product-code baseline is `a8a696bc`;
- the legacy `feat/mvp-remaining-tracks` branch at `900b936a`.

This file is the status source of truth for the active PR stack. The legacy branch is
retained only for comparison and must not override evidence in PR #2 or PR #3.
A checkmark means the production path is wired and the named acceptance evidence exists.
`Partial` means useful implementation exists but the complete product guarantee is not
closed.

## P0 — Branch and review setup

- [x] PR #2 and PR #3 are open as a mergeable draft stack.
- [x] Current automated checks are green on both active heads; Windows-native is an
  intentional skip.
- [x] Inline review findings raised on the two PRs have implementation follow-ups.
- [ ] Attach final current-head browser evidence for the remaining Demo rows.
- [ ] Update draft status, request reviewers, and merge PR #2 before retargeting PR #3.
- [ ] Review unique commits on `feat/mvp-remaining-tracks`, cherry-pick only intentional
  survivors, then archive or delete that legacy branch. Do not merge it wholesale.

## P1 — Design records

- [ ] Add `designs/REMOTE_LOCAL_RUNNER.md` with the implemented discovery/create API,
  persistence model, compatibility boundary, and supported harness scope.
- [ ] Add `designs/LOCAL_RUNNER_PERMISSIONS.md` with the selected shell default,
  trusted-machine behavior, audit schema, approval ownership, and replica limitation.
- [x] Add `designs/TERMINAL_MIRRORING_ACCEPTANCE.md` with executable byte and lifecycle
  evidence.
- [ ] Add API examples for runner discovery, workspace selection, session creation,
  local actions, approvals, and terminal recovery.

P1 is final only after the shell default and alpha support statements are frozen.

## P2 — Runner capability protocol and discovery

- [x] Extend `HelloFrame` with optional capability fields and compatibility tests.
- [x] Retain runner capability metadata in the active tunnel session.
- [x] Expose owner-scoped `GET /v1/runners` discovery.
- [x] Return opaque workspace IDs plus display-only metadata; do not return raw roots.
- [x] Return harness, transport, tool-capability, version, OS, and architecture data.
- [x] Hide foreign runners from listing and status lookup.

## P3 — Local runner CLI and pairing

- [x] Reuse the existing `omnigent host` daemon model.
- [x] Persist runner identity/pairing state and workspace registration.
- [x] Provide status and stop/disconnect flows.
- Partial: tmux/git/Node and configured harness signals exist, but one unified readiness
  contract including shell and per-harness launch readiness remains open.

## P4 — Workspace registry

- [x] Add runner-side approved workspaces with stable opaque IDs.
- [x] Canonicalize roots and reject unknown IDs, absolute operation paths, traversal,
  and normal symlink escapes during resolution.
- [x] Seed and advertise display-only workspace summaries.
- [ ] Return bounded project metadata needed by the picker: git summary, shell state,
  per-harness readiness, and missing/degraded reasons.

## P5 — Canonical session binding

- [x] Define execution-mode, workspace, and policy label keys.
- [x] Accept `runner_id + workspace_id` in JSON and multipart session creation.
- [x] Reject `runner_id` mixed with `host_id` or a raw `workspace` path.
- [x] Call `validate_local_runner_binding` from both public create paths.
- [x] Validate owner, online state, workspace membership, and harness compatibility.
- [x] Persist `runner_id` on the conversation and opaque workspace/policy labels.
- [x] Surface opaque binding data in create/session projections used by the web client.
- Partial: parent/child runner affinity and local-runner labels are inherited in the
  implementation; a final route-level matrix should explicitly cover fork, resume,
  reconnect, feature-flag denial, and foreign/unknown binding failures together.

The canonical binding is implemented. Do not open another PR whose main purpose is to
add runner discovery or `runner_id + workspace_id` creation.

## P6 — Native terminal launch in the selected workspace

- [x] Launch supported native terminals through the runner tunnel.
- [x] Publish and attach terminal resources through the authenticated public route.
- [x] Cover Codex-native plus at least one additional native harness in workspace launch
  tests.
- [x] Filter native harness advertisement when runner/workspace prerequisites are not
  truthful.
- Partial: finish the route-level canonical-binding matrix for every harness claimed by
  the MVP. Do not claim Gemini-native support without launch and reconnect evidence.

## P7 — Local actions gateway

- [x] Implement workspace-contained `read_file`, `list_dir`, `write_file`, and
  `run_shell`.
- [x] Add write diff preview and stale-content conflict detection.
- [x] Bound reads, command previews, diff previews, shell output, and shell duration.
- [x] Strip runner authentication secrets from child environments.
- [x] Implement strict Bubblewrap mode and truthful trusted-machine fallback labeling.
- [x] Keep `search_files`, `git_status`, `git_diff`, and `apply_patch` outside the
  advertised gateway capability contract.
- Partial: select and document the supported/default shell guarantee and align all
  preset and approval copy with it.
- [ ] Add a maximum write payload/request size and a bounded `list_dir` result.
- [ ] Re-resolve securely after approval and use no-follow, race-safe, atomic write
  semantics with symlink-swap regression tests.
- [ ] Implement `apply_patch` only if it receives the same preview, authorization,
  race-safety, and audit guarantees; otherwise keep it unadvertised.

## P8 — Permission, policy, and audit integration

- [x] Add manual, assisted, and auto policy values with fail-closed fallback.
- [x] Ask-gate side-effectful actions and enforce owner-only resolution.
- [x] Enforce read-only versus interactive terminal permissions before proxying.
- [x] Publish local-action lifecycle events and upsert terminal outcomes by exact
  `action_id`.
- [x] Persist an explicit allowlist with bounded value redaction.
- [x] Exclude write content, diff preview, stdout/stderr, tokens, absolute home paths,
  and raw command arguments from persisted history.
- [x] Persist `command_summary` as only the redacted executable token, capped at 80
  characters.
- [ ] Add log-capture tests proving server/runner logs omit bearer tokens, auth headers,
  full commands, file contents, output, and absolute home paths.
- [ ] State single-replica approval support for alpha or move pending approvals to a
  shared store.

## P9 — Runner UX

- [x] Fetch and type the canonical owner-scoped runner response.
- [x] Provide a runner/workspace picker using opaque IDs.
- [x] Submit `runner_id + workspace_id + local_runner_policy` without a raw path.
- [x] Disable obvious offline, empty-workspace, and harness-incompatible choices.
- [x] Show runner status and basic capability information.
- Partial: add bounded project metadata, unified readiness, and richer degraded-state
  explanations.

## P10 — Terminal parity and reconnect acceptance

- [x] Build a live authenticated public WebSocket fixture crossing server, multiplexed
  runner tunnel, runner attach route, and a real tmux pane.
- [x] Test input/output, initial capture, resize, multiline paste, UTF-8, control keys,
  Ctrl-C, alternate screen, and rapid ordered output.
- [x] Test read-only observation, interactive denial, runner-offline versus terminal
  exit, unsupported transport, reconnect, duplicate-I/O prevention, and stale-generation
  rejection.
- [x] Add server and browser-side bounded reconciliation settlement.
- [x] Preserve independent main and rail terminal selections and retain exited state.
- [ ] Add a real browser page-reload/SSE-bootstrap test while offline, followed by
  recovery on the same session.
- [ ] Decide whether PTY parity is a supported product contract; add its gate only if it
  remains supported.
- [ ] Capture final current-head browser evidence for automatic reconnect and the
  distinct terminal-exited state.

## P11 — Observability

- [x] Emit bounded local-action and approval-decision metrics.
- [ ] Add structured runner connect/disconnect/reconnect logs.
- [ ] Add terminal attach transport and close-code metrics.
- [ ] Add workspace validation and capability-mismatch metrics.
- [ ] Add a diagnostics/admin projection for live runner readiness.
- [ ] Add log-secrecy capture tests.

## P12 — Documentation and rollout

- [x] Keep the feature flag off by default and expose it in `/v1/info`.
- [x] Add named local-action and terminal E2E workflow gates.
- [ ] Add user pairing/workspace-selection documentation.
- [ ] Add admin enablement, replica limitation, recovery, and retention documentation.
- [ ] Add security documentation for policy modes and both shell guarantees.
- [ ] Add troubleshooting for runner offline, tmux/Bubblewrap missing, harness mismatch,
  capability mismatch, and reconnect.
- [ ] Add a manual QA script covering two users, denial, reconnect, reload, and secret
  checks.
- [ ] Map dev/alpha/beta gates to branch protection and publish release notes only after
  the alpha gate is green.

## Actual remaining order

1. Finish the current-head browser evidence and promote/merge PR #2, then retarget and
   promote PR #3.
2. `fix(local-actions): harden race-safe bounded workspace writes`.
3. Freeze the shell default and permission/audit support statements; update product copy
   and design records.
4. Add the literal browser reload/SSE acceptance case.
5. Complete readiness UX, observability, log-secrecy tests, and release documentation.
6. Reconcile and retire `feat/mvp-remaining-tracks` after intentionally preserving any
   unique non-overlapping fixes.
