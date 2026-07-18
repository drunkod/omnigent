# T09 — Runner UX

T09 is the web product track for local runners. It is **blocked** until T10 freezes the
canonical discovery and create contracts.

## Dependencies

- **T10 step 01:** one owner-scoped runner discovery response and public session create
  using `runner_id + workspace_id`.
- **T10 step 04:** truthful operation/readiness capabilities.
- Top-level `/v1/info.remote_local_runner` remains the feature gate.

Do not build the picker by round-tripping `path_label`, by sending a raw local path, or
by treating `host_id` as a runner identifier.

## Steps

1. `step-01-runner-list-fetch.md` — type and fetch the canonical runner discovery
   projection with `authenticatedFetch`.
2. `step-02-workspace-picker.md` — choose runner, opaque workspace ID, and policy;
   submit `runner_id + workspace_id + local_runner_policy`.
3. `step-03-capability-dashboard.md` — show truthful harness, terminal, workspace, and
   degraded-readiness data.

Steps are sequential within T09. T09 can run in parallel with T11 approval UI and T12
terminal E2E after T10 is complete.

## Done when

With the feature enabled, an owner can select an online runner and one advertised
workspace, create a session without exposing a local absolute path, see the persisted
local-runner/workspace badge after refresh, and inspect truthful capability/degraded
state. With the feature disabled, none of the local-runner UX renders or fetches.
