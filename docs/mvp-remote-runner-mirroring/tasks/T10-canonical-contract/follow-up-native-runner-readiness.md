# T10 Follow-up — Native runner readiness and multi-root binding

## Status

Post-T10 hardening. This does not block T11's typed approval UI, but it blocks
claims that native local-runner execution is fully ready across credentials,
multiple workspace roots, and release CI.

## Verified remaining gaps

1. Native Codex readiness currently proves that the executable is discoverable,
   but not that the runner has usable authentication/provider configuration.
2. Native terminal cwd still depends on a process-wide legacy workspace value.
   The current hello correctly fails closed for ambiguous multi-root runners,
   but it does not implement per-session `workspace_id` resolution.
3. The focused hello regression tests exist on the feature branch, but no
   pull-request workflow run is attached to the current head.

## Step A — Credential/provider readiness

### Goal

Do not present `codex-native` as ready merely because `shutil.which("codex")`
succeeds.

### Contract

Separate readiness signals:

- `installed`: executable is resolvable;
- `configured`: a non-secret credential/provider readiness probe succeeds;
- `ready`: required binary, workspace, terminal transport, and configuration
  prerequisites are all true;
- `reason`: safe machine-readable reason such as
  `binary_missing`, `workspace_ambiguous`, `auth_missing`, or
  `provider_unavailable`.

Never return tokens, credential paths, provider secrets, or raw CLI output in
the hello frame or runner discovery API.

### Probe rules

- Prefer a documented non-interactive Codex status/config command when it can
  run without network side effects and without exposing secrets.
- Bound probe duration and output.
- Cache briefly, then re-probe on reconnect or explicit refresh.
- When no reliable safe probe exists, advertise installation separately and
  surface a specific actionable startup error. Do not label the harness fully
  ready.
- Distinguish authentication/configuration failures from generic
  `native_terminal_start_failed` in the UI while keeping sensitive runner log
  details server-side.

### Tests

- binary absent → not installed/not ready;
- binary present, credentials absent → installed but not configured;
- configured fixture → ready;
- timed-out or malformed probe → safe unavailable reason;
- probe output containing a secret never reaches API/UI/log assertions.

## Step B — Per-session multi-root resolution

### Goal

Resolve the selected opaque workspace locally for each assigned session and
remove native terminal dependence on a process-wide cwd fallback.

### Runner assignment flow

1. Server sends `workspace_id` on runner `POST /v1/sessions`.
2. Runner validates it against its local `WorkspaceRegistry`.
3. Runner stores a per-session binding containing the canonical local root.
4. Harness spawn, native terminal launch, filesystem tools, and local actions
   resolve cwd from that same binding.
5. Session deletion/runner release removes the cached binding.

The server stores only opaque IDs and display labels. It never receives or
reconstructs the absolute runner path.

### Failure behavior

- unknown workspace ID → typed `workspace_not_found` before harness spawn;
- removed/unavailable root → typed runner readiness failure;
- runner reconnect revalidates existing assignments before relaunch;
- no fallback from a missing per-session binding to another root or arbitrary
  process cwd;
- old/new version skew may use the legacy single-root fallback only when exactly
  one root exists and the contract is explicitly detected.

### Tests

- two roots, two sessions select different roots and launch in the correct cwd;
- unknown ID never starts a terminal;
- reconnect restores the same opaque binding;
- root removal fails closed;
- child/fork/resume inherits or explicitly rebinds according to the session
  contract;
- server snapshots and logs contain no absolute runner root.

## Step C — Required CI evidence

Add focused pull-request jobs covering:

- runner hello workspace/readiness tests;
- server runner-discovery and session-binding integration;
- native Codex startup failure classification;
- multi-root per-session cwd acceptance after Step B lands.

Suggested required job names:

- `local-runner-capability-contract`
- `local-runner-session-binding`
- `native-codex-readiness`

## Done when

- native Codex discovery distinguishes installed, configured, and ready without
  leaking secrets;
- startup errors are specific and actionable;
- multi-root runners resolve `workspace_id` per session without a global cwd;
- old/new skew remains fail-closed; and
- named CI jobs execute on pull requests touching runner capability or binding
  code.
