# T08 — Permissions, policy presets, and the security test suite (steps)

Implementation-ready steps for `T08-permissions-policies-tests.md`, verified
against the codebase at `5565d9bd` (branch `feat/mvp-secure-permissions`).
Follows the T07 steps pattern: one PR-sized slice per step, in order.

Ground truth already in place (do NOT re-implement):

- `PolicyMode` enum (`manual`/`assisted`/`auto`) lives in
  `omnigent/policies/types.py`; string values are API contract.
- The runner already reads the mode label per action:
  `omnigent/runner/tool_dispatch.py` reads
  `omnigent.local_runner_policy` and defaults to `MANUAL`
  (covered by `tests/runner/test_local_runner_policy_binding.py`).
- Server label keys live in `omnigent/server/session_binding.py`
  (`LOCAL_RUNNER_POLICY_LABEL_KEY`).
- Runner-side audit publishing exists:
  `omnigent/runner/app.py::_publish_local_action_audit` emits
  `session.local_action` events from `AuditRecord.to_event()`.
- Local-action approvals ride the existing `mcp_elicitation` event flow:
  `omnigent/runner/app.py::_request_local_action_approval` POSTs an
  elicitation whose `data` carries `kind` + `policy_mode`, then parks on
  `omnigent/runner/pending_approvals.wait_for_user_approval`.
- `get_session_owner_id` (LEVEL_OWNER) exists in
  `omnigent/server/routes/_auth_helpers.py`.
- `ErrorCode.FORBIDDEN` maps to HTTP 403 (`omnigent/errors.py`).

## Steps

1. `step-01-policy-presets.md` — preset catalog + label application.
2. `step-02-owner-only-approvals.md` — server-side owner gate on
   local-action approval resolution.
3. `step-03-audit-sanitization.md` — server-side redaction of persisted
   `session.local_action` events.
4. `step-04-feature-flag-telemetry.md` — `remote_local_runner` capability
   flag + P11 counters.
5. `step-05-security-test-suite.md` —
   `tests/server/integration/test_remote_local_runner_permissions.py`.
6. `step-06-audit-persistence.md` — durable `session.local_action`
   conversation items (P8's last open box).
7. `step-07-telemetry-wiring.md` — permission counters via OTel
   (P11 subset).

## Done when

- Three presets resolvable to raw `PolicyMode` label values; unknown or
  invalid label values fall back to MANUAL (already runner behavior).
- Only the session owner can approve/deny a local action; collaborators
  get 403 server-side, before any runner forward.
- Persisted audit events contain no file contents, diffs, command output,
  or tokens.
- The integration suite in step-05 is green.

## Sequencing note

Steps 01–04 are independent of each other and can be done in any order
(or in parallel). Step 05 tests all of them, so it lands last — but write
its test file skeleton early and mark cases `xfail` to drive the work.
