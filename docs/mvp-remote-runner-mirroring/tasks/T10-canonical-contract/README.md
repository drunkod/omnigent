# T10 — Stage 1 blockers: canonical contracts

T10 is the sequential critical path created by the full-branch architectural review.
All remaining product UI and release claims depend on the contracts frozen here.

## Verified starting state

- Public session creation still uses `host_id + workspace` for the host-launch flow.
- `session_binding.py` has helper-level `runner_id + workspace_id` validation and label
  helpers without a production session-create caller.
- The current web hosts model does not provide the canonical owner-scoped runner and
  opaque-workspace discovery shape needed by that create contract.
- Direct file operations are workspace-contained, but `run_shell` resolves only `cwd`
  before invoking arbitrary shell text.
- Persisted local-action data is open-ended and may retain raw command summaries or
  path values despite exact-key sanitization.
- `search_files`, `git_status`, and `git_diff` are advertised near gateway actions but
  are served through a separate environment-filesystem path.

## Steps — strict order

1. `step-01-canonical-session-binding.md`
   - freeze owner-scoped runner discovery;
   - wire `runner_id + workspace_id` into public session creation;
   - keep host-launch `host_id + workspace` separate;
   - cover snapshot, child/fork/resume, and reconnect.
2. `step-02-shell-security-contract.md`
   - choose strict OS-sandbox mode or trusted-machine shell mode;
   - implement/document the selected guarantee;
   - remove any stronger claims.
3. `step-03-audit-schema-freeze.md`
   - replace open-ended persistence with an allowlisted bounded schema;
   - redact by value and add log/history secret tests;
   - add limits and race-safe revalidation.
4. `step-04-capability-truthfulness.md`
   - give every advertised action one authorization/workspace/audit path; or
   - trim the advertisement.

A later step must not silently redesign an earlier contract. If a step discovers that
an earlier decision is invalid, reopen and update the earlier document and its tests.

## Stage 2 unlocked by T10

- `../T09-runner-ux/` — picker and capability UI.
- `../T11-approval-ui.md` — approval/diff UI and approval-flow E2E.
- `../T12-terminal-parity-e2e.md` — real terminal parity and reconnect E2E.

T09 needs steps 01 and 04. T11 needs steps 02 and 03. T12 may begin its fixture after
step 01 and then proceed in parallel.

## Explicit support boundary

Pending local-action approval ownership is currently process-local. For alpha, either:

- document and enforce single-replica support for sessions with pending approvals; or
- move approval ownership/resolution state to shared storage.

The rollout documents must choose one. Do not imply multi-replica approval safety by
omission.

## Done when

- the checklist P5/P7/P8 items reference route/integration evidence rather than helper
  existence;
- no local-runner create request accepts or reconstructs a raw local workspace path;
- shell behavior matches its documented security mode;
- persisted/logged audit data passes realistic secret tests;
- capability discovery is truthful; and
- T09/T11/T12 can implement against stable contracts without probing or guessing.
