# T07 — Terminal mirroring UI: runner status, workspace picker, reconnect

Implements plan `03-terminal-mirroring-ui-plan.md` Tasks UI-1…UI-5 and checklist P9.

Ground truth (verified against current code):

- `web/src/components/blocks/TerminalSession.ts` **already implements** the xterm ↔
  attach-WebSocket bridge with `transport=control|pty` support, close-code
  classification (transport-shaped vs 4xxx app closes), resize, CSI-u synthesis, and
  native-selection handling. Do **not** write a new terminal protocol — extend this.
- Terminal panels live in `web/src/shell/` (`TerminalsPanel.tsx`, `MainTerminalView.tsx`,
  `useTerminalStatuses.ts`); block cards in `web/src/components/blocks/`.
- Server contracts consumed here: `GET /v1/runners` capability summary (T01),
  session labels `omnigent.workspace_id` / `omnigent.execution_mode` (T04),
  `session.runner_state` / `session.terminal_state` events + attach close codes
  4503/4404/4405/4406 (T06).

## 1. Shared types — `web/src/lib/remoteRunner.ts`

```typescript
// Mirrors omnigent/entities/terminal_state.py — keep in sync by hand
// (values are asserted in an e2e contract test, see §6).
export type TerminalUiState =
  | "terminal_unknown"
  | "terminal_starting"
  | "terminal_running"
  | "terminal_detached"
  | "terminal_exited"
  | "runner_offline"
  | "runner_reconnected"
  | "terminal_relaunching"
  | "terminal_failed";

export interface RunnerWorkspace {
  workspace_id: string;
  display_name: string;
  path_label: string;
  capabilities: string[];
}

export interface RunnerInfo {
  runner_id: string;
  online: boolean;
  runner_version?: string;
  mode?: "local" | "managed" | "in_process";
  os?: string;
  arch?: string;
  harnesses: string[];
  terminal_transports: string[];
  workspaces: RunnerWorkspace[];
}

/** Attach close-code → UI state mapping (T06 contract). */
export function stateFromAttachClose(code: number): TerminalUiState | null {
  switch (code) {
    case 4503: return "runner_offline";
    case 4404: return "terminal_exited";
    case 4405: return "terminal_detached";
    default: return null; // transport-shaped closes handled by existing retry logic
  }
}

export async function fetchRunners(): Promise<RunnerInfo[]> {
  const resp = await fetch("/v1/runners");
  if (!resp.ok) throw new Error(`runners fetch failed: ${resp.status}`);
  return (await resp.json()).data as RunnerInfo[];
}
```

## 2. Runner status hook + panel (UI-1)

`web/src/hooks/useRunnerState.ts`:

```typescript
import { useEffect, useState } from "react";
import type { TerminalUiState } from "../lib/remoteRunner";

export interface RunnerSessionState {
  state: TerminalUiState | "unknown";
  runnerId: string | null;
  lastChangeAt: number;
}

/**
 * Track runner liveness for one session from the session event stream.
 * Subscribes to `session.runner_state` (T06) on the existing session
 * SSE/WS event source; falls back to "unknown" until the first event.
 */
export function useRunnerState(sessionId: string, events: EventSource): RunnerSessionState {
  const [state, setState] = useState<RunnerSessionState>({
    state: "unknown", runnerId: null, lastChangeAt: 0,
  });
  useEffect(() => {
    const onEvent = (e: MessageEvent) => {
      const body = JSON.parse(e.data);
      setState({ state: body.state, runnerId: body.runner_id, lastChangeAt: Date.now() });
    };
    events.addEventListener("session.runner_state", onEvent);
    return () => events.removeEventListener("session.runner_state", onEvent);
  }, [sessionId, events]);
  return state;
}
```

`web/src/shell/RunnerStatusBadge.tsx` (rendered in the session header next to the
agent name; also reused by the sidebar):

```tsx
import type { RunnerInfo } from "../lib/remoteRunner";
import type { RunnerSessionState } from "../hooks/useRunnerState";

export function RunnerStatusBadge({
  executionMode, runner, liveState,
}: {
  executionMode: "local_runner" | "managed" | null;
  runner: RunnerInfo | null;
  liveState: RunnerSessionState;
}) {
  if (executionMode !== "local_runner") return null;
  const offline = liveState.state === "runner_offline" || (runner !== null && !runner.online);
  return (
    <span
      className={`runner-badge ${offline ? "runner-badge--offline" : "runner-badge--online"}`}
      title={
        runner
          ? `${runner.runner_id} · v${runner.runner_version} · ${runner.os}/${runner.arch}`
          : "local runner"
      }
    >
      <span className="runner-badge__dot" aria-hidden />
      {offline ? "Local runner offline" : "Local runner"}
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

Acceptance-relevant detail: the offline copy must say the session is **preserved**,
never implying loss (plan UI-1).

## 3. Workspace picker in the new-session flow (UI-2)

`web/src/components/NewSessionRunnerPicker.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { fetchRunners, type RunnerInfo, type RunnerWorkspace } from "../lib/remoteRunner";

export interface RunnerSelection {
  runnerId: string | null;
  workspaceId: string | null;
}

export function NewSessionRunnerPicker({
  harness, value, onChange,
}: {
  harness: string;                      // resolved harness of the chosen agent
  value: RunnerSelection;
  onChange: (next: RunnerSelection) => void;
}) {
  const [runners, setRunners] = useState<RunnerInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRunners().then(setRunners).catch((e) => setError(String(e)));
  }, []);

  const localRunners = useMemo(
    () => (runners ?? []).filter((r) => r.mode === "local" && r.online),
    [runners],
  );
  const selected = localRunners.find((r) => r.runner_id === value.runnerId) ?? null;
  const harnessSupported = selected == null || selected.harnesses.includes(harness);

  if (error) return <p className="picker-error">Couldn’t load runners: {error}</p>;
  if (runners === null) return <p>Loading runners…</p>;
  if (localRunners.length === 0) {
    return (
      <div className="picker-empty">
        <p>No local runner is connected.</p>
        <p>
          On the machine with your code, run{" "}
          <code>omnigent host --server {window.location.origin} --workspace ~/your-project</code>
        </p>
      </div>
    );
  }

  return (
    <fieldset className="runner-picker">
      <label>
        Run on
        <select
          value={value.runnerId ?? ""}
          onChange={(e) =>
            onChange({ runnerId: e.target.value || null, workspaceId: null })
          }
        >
          <option value="">This server (managed)</option>
          {localRunners.map((r) => (
            <option key={r.runner_id} value={r.runner_id}>
              {r.runner_id} — {r.os}/{r.arch}
            </option>
          ))}
        </select>
      </label>

      {selected && (
        <label>
          Workspace
          <select
            value={value.workspaceId ?? ""}
            onChange={(e) => onChange({ ...value, workspaceId: e.target.value || null })}
          >
            <option value="" disabled>Select a workspace…</option>
            {selected.workspaces.map((ws: RunnerWorkspace) => (
              <option key={ws.workspace_id} value={ws.workspace_id}>
                {ws.display_name} ({ws.path_label})
              </option>
            ))}
          </select>
        </label>
      )}

      {!harnessSupported && (
        <p className="picker-warning" role="alert">
          This runner doesn’t have the {harness} CLI installed — install it there or
          pick a different agent.
        </p>
      )}
    </fieldset>
  );
}
```

Session create request then includes `runner_id` + `workspace_id` (T04). Disable the
create button while `runnerId && !workspaceId` or `!harnessSupported`.

## 4. Terminal panel: transport default, reconnect states (UI-3)

Changes to the existing attach flow (`TerminalSession.ts` + `MainTerminalView.tsx`):

1. **Transport default**: when the session's runner advertises `"control"` in
   `terminal_transports` (T01), pass `transport=control`; else `pty`. Keep a debug
   override in the existing dev settings store.

```typescript
export function attachQuery(opts: {
  transports: string[];             // runner-advertised
  debugOverride?: "control" | "pty";
  readOnly: boolean;
}): string {
  const transport =
    opts.debugOverride ?? (opts.transports.includes("control") ? "control" : "pty");
  const params = new URLSearchParams({ transport });
  if (opts.readOnly) params.set("read_only", "true");
  return params.toString();
}
```

2. **Close-code handling**: in the existing `close` handler (which already separates
   transport-shaped closes for retry), consult `stateFromAttachClose(code)` first:

```typescript
this.ws.addEventListener("close", (e) => {
  const mapped = stateFromAttachClose(e.code);
  if (mapped === "runner_offline") {
    this.emit({ kind: "runner_offline" });      // panel shows offline overlay, no redial loop
    return;
  }
  if (e.code === 4406) {                         // transport unsupported → one pty retry
    this.emit({ kind: "retry_with", transport: "pty" });
    return;
  }
  if (mapped) { this.emit({ kind: "state", state: mapped }); return; }
  // ...existing transport-shaped retry logic unchanged...
});
```

3. **Buffer stability across reconnect**: keep the xterm instance mounted while
   showing the offline/reconnecting overlay; on `session.runner_state:
   runner_reconnected` (T06), re-dial the attach URL. Control-mode re-attach re-seeds
   from `capture-pane` server-side, so history repaints without clearing the buffer.

4. **Read-only badge**: when the viewer isn't the owner, the panel passes
   `readOnly: true` and renders a "view only" chip (permission behavior itself is
   unchanged — `terminal_attach.py` already enforces it).

## 5. Approval + diff cards for local actions (UI-5)

Local-action approvals arrive through the **existing** approval-card event flow
(T05 wires the gateway into `pending_approvals`). Add a renderer for the gateway's
payload in `web/src/components/blocks/LocalActionApprovalCard.tsx`:

```tsx
export interface LocalActionApproval {
  approval_id: string;
  kind: "write_file" | "apply_patch" | "run_shell" | string;
  policy_mode: "manual" | "assisted" | "auto";
  risk_flags: string[];
  path_summary: string[];
  command_summary?: string;
  cwd?: string;
  diff_preview?: string;              // unified diff (write/apply_patch only)
}

export function LocalActionApprovalCard({
  approval, onDecide,
}: {
  approval: LocalActionApproval;
  onDecide: (approvalId: string, approved: boolean) => void;
}) {
  const isShell = approval.kind === "run_shell";
  return (
    <div className="approval-card approval-card--local">
      <header>
        <strong>{isShell ? "Run command on your machine" : "Edit file on your machine"}</strong>
        <span className="approval-card__mode">{approval.policy_mode} mode</span>
        {approval.risk_flags.map((f) => (
          <span key={f} className={`risk-chip risk-chip--${f}`}>{f}</span>
        ))}
      </header>

      {isShell ? (
        <pre className="approval-card__command">
          <span className="approval-card__cwd">{approval.cwd ?? "."} $</span>{" "}
          {approval.command_summary}
        </pre>
      ) : (
        <>
          <p className="approval-card__paths">{approval.path_summary.join(", ")}</p>
          {approval.diff_preview && (
            <DiffView unified={approval.diff_preview} /* reuse existing diff viewer */ />
          )}
        </>
      )}

      <footer>
        <button onClick={() => onDecide(approval.approval_id, false)}>Deny</button>
        <button className="primary" onClick={() => onDecide(approval.approval_id, true)}>
          Approve
        </button>
      </footer>
    </div>
  );
}
```

Completed actions render a compact result line (status, duration, exit code) from the
audit events (`session.local_action` stream), appended to the session event feed.

## 6. Tests

Component tests (vitest, alongside existing `*.test.tsx`):

```typescript
// remoteRunner.test.ts
import { attachQuery, stateFromAttachClose } from "./remoteRunner";

test("control preferred when advertised", () => {
  expect(attachQuery({ transports: ["control", "pty"], readOnly: false }))
    .toBe("transport=control");
});
test("pty fallback when control absent", () => {
  expect(attachQuery({ transports: ["pty"], readOnly: true }))
    .toBe("transport=pty&read_only=true");
});
test("close-code mapping matches T06 contract", () => {
  expect(stateFromAttachClose(4503)).toBe("runner_offline");
  expect(stateFromAttachClose(4404)).toBe("terminal_exited");
  expect(stateFromAttachClose(4405)).toBe("terminal_detached");
  expect(stateFromAttachClose(1006)).toBeNull();
});
```

Playwright e2e (`tests/e2e_ui/sessions/test_remote_local_runner.py`):

- new session flow shows picker; no-runner state shows CLI setup instructions;
- create with runner+workspace → session header shows `Local runner` badge and
  workspace label;
- kill fake runner tunnel → offline banner appears, terminal overlay says preserved;
- reconnect → banner clears, terminal repaints (assert prompt text still present);
- write-file approval card shows diff before approval; deny → file unchanged event.

Visual regression snapshots: terminal panel (normal, offline overlay), approval card,
workspace picker (plan 03 list).

## Acceptance checklist

- [ ] `RunnerInfo`/`TerminalUiState` types mirror server contracts; contract test pins values.
- [ ] Runner badge with offline recovery copy; never implies session loss.
- [ ] Workspace picker: owned online local runners only, harness warning, CLI empty-state.
- [ ] Attach uses `transport=control` when advertised, `pty` fallback + 4406 retry.
- [ ] Offline/reconnect overlay keeps xterm buffer; re-dial on `runner_reconnected`.
- [ ] Local-action approval card with diff preview / command+cwd; deny leaves no change.
- [ ] Component + e2e + visual tests above.
