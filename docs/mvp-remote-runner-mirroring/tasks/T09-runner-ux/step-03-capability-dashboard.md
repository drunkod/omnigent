# T09 Step 03 — Runner capability and degraded-state dashboard

Depends on T09 step 01 and T10 step 04. This panel is presentation over the canonical
runner discovery model; it must not invent readiness or imply that an advertised tool
has stronger policy/audit guarantees than its real dispatch path.

## Display model

For each runner show:

- display name and opaque `runner_id` only in diagnostic detail;
- online/offline/reconnecting state;
- runner version and OS/architecture when available;
- configured/ready harnesses;
- terminal transports;
- approved workspaces by display name/path label, never absolute root;
- truthful local action/tool capabilities after T10 step 04;
- specific degraded reasons when the server provides them.

Prefer explicit fields such as:

```typescript
interface RunnerDegradedReason {
  code:
    | "runner_offline"
    | "tmux_missing"
    | "shell_sandbox_unavailable"
    | "harness_missing"
    | "workspace_missing"
    | "version_mismatch";
  detail?: string;
}
```

Do not derive `tmux_missing` merely from an empty transport list if the API can state a
more precise reason. If the server does not expose a needed diagnostic, add a bounded
server projection rather than guessing client-side.

## Placement

Use the existing settings/infrastructure pattern. A “Runners” section in settings is
the smallest alpha surface. Reuse the same `useLocalRunners` data source as the picker;
do not add a second poll loop.

## Required states and copy

- **No runner paired:** pairing instructions and documentation link.
- **Offline:** retain the card, disable new-session selection, show last-seen only when
  supplied by the server.
- **No workspaces:** explain how to approve one locally.
- **No terminal transport:** show the server-provided reason.
- **Harness unavailable:** name the missing harness and keep unrelated harnesses usable.
- **Strict shell requested but unavailable:** fail closed and show the missing sandbox
  requirement.
- **Trusted-machine shell mode:** display that owner approval grants normal user-level
  shell access; do not label it workspace-sandboxed.
- **Version mismatch:** name the minimum compatible runner/server version when known.

## Tests

- one card per runner with opaque workspace summaries;
- no absolute path rendered or serialized in component snapshots;
- offline and no-workspace states are actionable;
- degraded reasons map to stable copy;
- shell-mode copy matches T10 step 02;
- capability names shown are exactly the T10 step 04 advertisement;
- the panel and picker share one fetch/store path;
- feature-off mode renders nothing.

## Manual QA

Pair a real runner, add/remove a workspace, stop/restart the runner, remove tmux or a
harness in a disposable environment, and verify the panel changes without exposing
secrets or local roots.

## Done when

The panel is a truthful diagnostic projection of the canonical runner contract and all
of its degraded states are explicit rather than inferred from missing fields.
