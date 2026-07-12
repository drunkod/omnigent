# T11 Step 03 — Resolution flow and side-effect E2E

## Goal

Prove that local-action approval is owner-authoritative, race-safe, and
at-most-once by asserting real filesystem/process side effects rather than only
HTTP responses or UI state.

## Prerequisites

- Step 01 typed approval payload is stable.
- Step 02 shell/write cards submit through the existing session-scoped resolve
  endpoint.
- The runner gateway still owns policy evaluation, approval waiting, workspace
  resolution, and execution.

## Test fixture

Create a deterministic Linux fixture with:

- a temporary approved workspace registered under an opaque `workspace_id`;
- a real runner-local `LocalActionGateway` or a tunnel-backed runner app;
- a session owner and a collaborator identity;
- a controllable approval waiter;
- a process launcher spy for denial cases;
- real filesystem writes for approval/conflict cases;
- no external network dependency.

Use strict shell mode in the real shell test when `bwrap` is available. Keep a
trusted-machine launcher-spy test for platforms where the sandbox fixture cannot
run. Do not silently skip the guarantee assertion.

## Required cases

### 1. Owner approves write

- create a pending write with a reviewed diff;
- approve as owner;
- assert the expected bytes are written exactly once;
- assert audit/status edges reach requested → approved → completed;
- replay the same resolution and prove no second execution.

### 2. Owner denies write

- capture the original file bytes and metadata needed by the fixture;
- deny as owner;
- assert the file remains byte-for-byte unchanged;
- assert no temporary replacement file remains;
- assert denied status is published.

### 3. Collaborator cannot resolve

- attempt approval as a collaborator with edit/read access but not ownership;
- expect 403;
- assert the waiter remains pending;
- assert the owner can still resolve the same elicitation afterward;
- assert the card/store remains pending after the collaborator failure.

### 4. Owner denies shell

- deny a pending shell action;
- assert the process launcher was never called;
- assert no marker file/process side effect exists;
- assert denied status is published.

### 5. Target changes while pending

- produce a write diff from initial content;
- mutate the target before owner approval completes;
- approve;
- expect conflict;
- assert the newer content remains unchanged;
- assert no stale reviewed content is written.

### 6. Runner disconnects while pending

- disconnect or invalidate the bound runner while the prompt is unresolved;
- assert the UI receives the documented unavailable/retryable state;
- assert a stale resolve cannot execute on another runner;
- reconnect behavior must either restore the same authoritative pending action
  or require a fresh action; document which contract is chosen.

### 7. Secret-bearing fixture

Use realistic secret-shaped values in command/file content, for example a
Bearer token and private-key marker.

Assert:

- only the runner-produced redacted/bounded preview reaches the UI;
- persisted conversation history omits live command/diff previews;
- persisted audit records contain only the frozen allowlisted summaries;
- server/runner logs used by the test do not contain the fixture secret.

### 8. Double click and replay

- submit two near-simultaneous owner approvals and replay the live event;
- assert exactly one waiter resolution wins;
- assert the action executes once;
- assert the completed prompt is not resurrected by snapshot hydration.

## UI/store integration assertions

- duplicate snapshot + live request yields one card;
- wrong-session resolution is ignored;
- terminal-side resolution clears the matching card;
- a failed collaborator submit rolls optimistic state back to pending;
- a completed prompt never reappears after refresh.

## Suggested test layers

1. **Runner unit/integration**
   - gateway side effects, conflict, denial, and at-most-once waiter behavior.
2. **Server route integration**
   - owner/collaborator authorization, pending snapshot, terminal resolution,
     and replay/tombstone behavior.
3. **Web reducer/component**
   - dedupe, rollback, resolution, refresh, and safe rendering.
4. **One tunnel-backed acceptance test**
   - browser-shaped request → server → runner → real temporary workspace →
     resolution event.

## CI gates

Add named required Linux jobs so failures are visible by contract:

- `local-action-approval-contract`
- `local-action-approval-side-effects`
- `web-local-action-approval`

The side-effect job must install/verify its sandbox prerequisite explicitly and
report a clear unsupported-platform result rather than passing without running
the strict-shell case.

## Done when

- every required case asserts state and side effects;
- denial, collaborator rejection, and conflict prove no execution occurred;
- replay/double-click proves at-most-once execution;
- refresh and terminal resolution cannot resurrect a prompt;
- secret fixtures are absent from persisted history, audit, and captured logs;
  and
- the named CI jobs run on pull requests touching the approval pipeline.
