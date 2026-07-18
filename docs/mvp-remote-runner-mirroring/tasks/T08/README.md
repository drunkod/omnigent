# T08 — Permissions, presets, persistence, and permission metrics

T08 has substantial implementation, but it is not the final security boundary. Use
`05-implementation-checklist.md` for status and T10 for reopened blockers.

## Landed and evidence-backed

- `PolicyMode` values `manual`, `assisted`, and `auto`, with invalid/missing labels
  falling back to `MANUAL`.
- Server-side owner-only resolution for tagged local-action approvals in the current
  process.
- Read-only versus interactive terminal attach authorization before runner proxying.
- Runner publication of `session.local_action` lifecycle events.
- Persistence of terminal local-action outcomes, upserted by `action_id`.
- Feature flag off by default, exposed as top-level `remote_local_runner` from
  `/v1/info`.
- `omnigent.local_action.total` and `omnigent.approval.decision_total` counters.

## Reopened by the architectural review

- **Shell guarantee:** `run_shell` contains `cwd`, not arbitrary command paths. T10
  step 02 must implement a real sandbox or document trusted-machine shell access.
- **Audit secrecy:** exact-key sanitization and an open-ended persisted model do not
  prove payload-free history. T10 step 03 replaces them with an allowlisted bounded
  schema and value-level secret tests.
- **Capability truthfulness:** search and git reads must converge on one audited
  authorization path or be removed from that advertisement. T10 step 04 owns this.
- **Distributed approvals:** pending approval ownership is process-local. Alpha must
  either state single-replica support or move this state to shared storage.
- **Observability:** only the two permission counters above are complete; tunnel,
  attach, mismatch, reconnect, diagnostics, and log-capture work remain P11.

## Original implementation slices

1. `step-01-policy-presets.md` — preset catalog and label resolution.
2. `step-02-owner-only-approvals.md` — server owner gate.
3. `step-03-audit-sanitization.md` — initial defense-in-depth key removal; superseded
   for final acceptance by T10 step 03.
4. `step-04-feature-flag-telemetry.md` — feature flag and initial metric plan.
5. `step-05-security-test-suite.md` — permission integration cases.
6. `step-06-audit-persistence.md` — terminal-outcome persistence mechanics.
7. `step-07-telemetry-wiring.md` — the two implemented permission counters.

## Current done-when

T08 may be called functionally landed only when:

- presets and current shell behavior have accurate UI/docs copy;
- owner approval and attach authorization tests remain green;
- T10 step 03 proves secrets, full commands, output, contents, and absolute home paths
  are absent from persisted history and logs;
- the rollout docs state the approval-replica limitation; and
- the checklist distinguishes implemented permission metrics from the still-open P11
  metrics.
