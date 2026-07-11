# T09 Step 02 — Workspace picker + execution-mode badge (Deferred B)

Track 2, step 2. Depends on step 01's `useHosts` + capability gate.
Adds the host/workspace picker to the new-session flow and an
execution-mode indicator to the session header. Server side is already
done: session create accepts `host_id` + `workspace` (validated via
`_validate_session_workspace`) and `local_runner_policy`
(`SessionCreateRequest`, schemas.py ~L1311; rejected 400 without a
host/inherited runner since `18bb38dc`).

## 1. Picker — `web/src/components/NewSessionRunnerPicker.tsx`

```tsx
import { useMemo } from "react";
import { useHosts } from "../hooks/useHosts";
import type { HostWorkspace } from "../lib/remoteRunner";

export interface RunnerSelection {
  hostId: string | null;
  workspaceId: string | null;
  policy: "manual" | "assisted" | "auto";
}

export const EMPTY_SELECTION: RunnerSelection = {
  hostId: null,
  workspaceId: null,
  policy: "manual",
};

export function NewSessionRunnerPicker({
  harness,
  enabled,
  value,
  onChange,
}: {
  harness: string; // resolved harness of the chosen agent
  enabled: boolean; // remote_local_runner capability (step 01)
  value: RunnerSelection;
  onChange: (next: RunnerSelection) => void;
}) {
  const { hosts, error } = useHosts(enabled);
  const online = useMemo(() => (hosts ?? []).filter((h) => h.online), [hosts]);
  const selected = online.find((h) => h.host_id === value.hostId) ?? null;
  const harnessSupported = selected == null || selected.harnesses.includes(harness);

  if (!enabled) return null;
  if (error) return <p role="alert">Couldn’t load hosts: {error}</p>;
  if (hosts === null) return <p>Loading hosts…</p>;
  if (online.length === 0) {
    return (
      <div>
        <p>No local runner is connected.</p>
        <p>
          On the machine with your code, run{" "}
          <code>omnigent host --server {window.location.origin} --workspace ~/your-project</code>
        </p>
      </div>
    );
  }

  return (
    <fieldset>
      <label>
        Run on
        <select
          value={value.hostId ?? ""}
          onChange={(e) =>
            onChange({ ...value, hostId: e.target.value || null, workspaceId: null })
          }
        >
          <option value="">This server (managed)</option>
          {online.map((h) => (
            <option key={h.host_id} value={h.host_id}>
              {h.display_name ?? h.host_id} — {h.os}/{h.arch}
            </option>
          ))}
        </select>
      </label>

      {selected && (
        <>
          <label>
            Workspace
            <select
              value={value.workspaceId ?? ""}
              onChange={(e) => onChange({ ...value, workspaceId: e.target.value || null })}
            >
              <option value="" disabled>Select a workspace…</option>
              {selected.workspaces.map((ws: HostWorkspace) => (
                <option key={ws.workspace_id} value={ws.workspace_id}>
                  {ws.display_name} ({ws.path_label})
                </option>
              ))}
            </select>
          </label>

          <label>
            Permissions
            <select
              value={value.policy}
              onChange={(e) =>
                onChange({ ...value, policy: e.target.value as RunnerSelection["policy"] })
              }
            >
              <option value="manual">Manual — ask before every write/command</option>
              <option value="assisted">Assisted — reads allowed, writes ask</option>
              <option value="auto">Auto — safe workspace actions allowed</option>
            </select>
          </label>
        </>
      )}

      {!harnessSupported && (
        <p role="alert">
          This runner doesn’t have the {harness} CLI installed — install it there
          or pick a different agent.
        </p>
      )}
    </fieldset>
  );
}
```

Create-button gating in the parent form:

```typescript
const createDisabled =
  (selection.hostId !== null && selection.workspaceId === null) || !harnessSupported;
```

Create request additions (only when a host is chosen):

```typescript
const body = {
  agent_id: agentId,
  ...(selection.hostId && {
    host_id: selection.hostId,
    workspace: workspacePathFor(selection), // path_label round-trip or ws id per API probe
    local_runner_policy: selection.policy,
  }),
};
```

Probe the create route once to confirm whether it wants `workspace`
(path) or a workspace id — `_validate_session_workspace` takes
`workspace`, so likely the path.

## 2. Execution-mode badge — `web/src/shell/ExecutionModeBadge.tsx`

The session snapshot exposes binding labels (T04/T05):

```tsx
export function ExecutionModeBadge({ labels }: { labels: Record<string, string> }) {
  const mode = labels["omnigent.execution_mode"];
  if (mode !== "local_runner") return null; // managed = no badge (default)
  const workspace = labels["omnigent.workspace_label"] ?? "local workspace";
  const policy = labels["omnigent.local_runner_policy"] ?? "manual";
  return (
    <span
      className="rounded border px-1.5 py-0.5 text-xs"
      title={`Runs on your machine in ${workspace} (${policy} mode)`}
    >
      local · {workspace}
    </span>
  );
}
```

Mount next to `RunnerStatusBadge` in `ChatHeader.tsx` (same store/props
plumbing).

## 3. Tests

```tsx
// NewSessionRunnerPicker.test.tsx — key cases
it("renders nothing when the capability is off", ...);
it("shows CLI setup instructions when no host is online", ...);
it("resets workspace when the host changes", ...);
it("flags an unsupported harness", ...);

// ExecutionModeBadge.test.tsx
it("is hidden for managed sessions", ...);
it("shows workspace label and policy tooltip for local sessions", ...);
```

e2e (deferred with the Playwright fixture): create with host+workspace →
header shows badge and workspace label; visual snapshot of the picker.

## Done when

- Flag-off servers render no picker and no badge.
- Create is blocked until a workspace is chosen for a host-bound session.
- The created session's header shows the local badge from labels alone
  (works after refresh — labels come from the snapshot, not client state).
