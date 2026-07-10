# Step 06 — Deferred scope (NOT in the T07 PR)

Content moved out of the original T07 file. Kept here so the code sketches
aren't lost; each item ships as its own slice.

## Why deferred

- **Workspace picker** depends on runner/workspace listing + validation
  (`GET /v1/runners`, approved workspace roots, harness-mismatch warning).
  The backend work plan treats runner listing/status and capability discovery
  as its own earlier phase — don't gate T07 on it. Target: **T07b/T09**.
- **Approval/diff UX** belongs to the permissions slice (T05/T08 policy and
  local-action approval), not reconnect lifecycle. Mixing it in makes one
  large PR spanning permission semantics.

---

## Deferred A — Runner list types + fetch (`web/src/lib/remoteRunner.ts` additions)

```typescript
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

export async function fetchRunners(): Promise<RunnerInfo[]> {
  const resp = await fetch("/v1/runners");
  if (!resp.ok) throw new Error(`runners fetch failed: ${resp.status}`);
  return (await resp.json()).data as RunnerInfo[];
}
```

## Deferred B — Workspace picker in new-session flow (plan UI-2)

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

Session create request then includes `runner_id` + `workspace_id` (T04).
Disable the create button while `runnerId && !workspaceId` or `!harnessSupported`.

e2e (deferred with it): new-session flow shows picker; no-runner state shows
CLI setup instructions; create with runner+workspace → header shows badge and
workspace label; workspace picker visual snapshot.

## Deferred C — Local-action approval + diff cards (plan UI-5, permissions slice)

Local-action approvals arrive through the **existing** approval-card event
flow (T05 wires the gateway into `pending_approvals`).
`web/src/components/blocks/LocalActionApprovalCard.tsx`:

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

Completed actions render a compact result line (status, duration, exit code)
from the `session.local_action` audit stream. e2e: write-file approval card
shows diff before approval; deny → file unchanged event. Visual snapshot of
the approval card.

## Deferred D — Full runner capability dashboard

Version, OS/arch, harnesses, transports, workspace label/path, last seen,
reconnect state — build after `/v1/runners` (or equivalent) is stable, likely
alongside Deferred B.
