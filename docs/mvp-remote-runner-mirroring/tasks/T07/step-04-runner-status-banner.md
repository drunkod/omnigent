# Step 04 — Minimal runner/session status banner

**Commit 4 of T07.** Small header/sidebar indicator. Deliberately minimal:
the full runner status panel (version, OS/arch, harnesses, transports,
workspace label/path, last seen) waits until `/v1/runners` capability
discovery is solid — that's its own earlier backend phase. Surface only what
the app already knows reliably:

```text
This session is using a local runner.
Runner is offline / reconnecting / reconnected.
Terminal is running / relaunching / exited / failed.
```

## Existing plumbing to reuse

`web/src/hooks/RunnerHealthProvider.tsx` already exposes per-session
runner-online / host-online maps (stream + scoped `/health` poll for the open
session). **Do not add another poller.** The lifecycle store (step-01) adds
the event-driven transitions; the banner merges both.

## Task

`web/src/shell/RunnerStatusBadge.tsx`, rendered in `ChatHeader.tsx` next to
the agent name (reused by the sidebar row):

```tsx
import { useTerminalLifecycleStore, selectRunnerState } from "@/store/terminalLifecycleStore";
import { useSessionRunnerOnline } from "@/hooks/RunnerHealthProvider"; // existing context

export function RunnerStatusBadge({ conversationId, executionMode }: {
  conversationId: string;
  executionMode: "local_runner" | "managed" | null;   // session label omnigent.execution_mode (T04)
}) {
  const lifecycle = useTerminalLifecycleStore(selectRunnerState(conversationId));
  const pollOnline = useSessionRunnerOnline(conversationId);  // health-poll fallback

  if (executionMode !== "local_runner") return null;

  // Event stream wins when it has spoken; the poll covers the cold-start
  // window before any lifecycle event arrives.
  const offline = lifecycle === "runner_offline" || (lifecycle === "online" && pollOnline === false);
  const reconciling = lifecycle === "runner_reconnected";

  const label = offline ? "Local runner offline"
    : reconciling ? "Reconnecting local runner"
    : "Local runner";

  return (
    <span className={`runner-badge runner-badge--${offline ? "offline" : reconciling ? "reconnecting" : "online"}`}>
      <span className="runner-badge__dot" aria-hidden />
      {label}
      {offline && (
        <span className="runner-badge__hint">
          Session is preserved — restart the runner with{" "}
          <code>omnigent host --server &lt;url&gt;</code> to continue.
        </span>
      )}
    </span>
  );
}
```

Copy rule (plan UI-1 acceptance): offline copy must say the session is
**preserved** — never imply loss.

Sidebar variant: same states, dot-only + tooltip. Optional terminal sub-line
in the header when any terminal in the conversation is non-running:

```text
Terminal relaunching   (spinner)
Terminal exited
Terminal failed
```

derived from `terminalStateById` — no new events, no new endpoints.

## What NOT to build here

- No runner picker.
- No capability card (harnesses/transports/workspaces).
- No `/v1/runners` list UI — step-06 defers it with the workspace picker.

## Acceptance

```text
managed sessions render no badge
local-runner session shows "Local runner" when healthy
runner_offline event -> offline badge + preserved copy (no session-loss wording)
runner_reconnected -> "Reconnecting local runner" until first terminal state
poll-detected offline (no event yet) still shows offline
```

Next: [step-05 — tests and manual QA](step-05-tests-and-manual-qa.md)
