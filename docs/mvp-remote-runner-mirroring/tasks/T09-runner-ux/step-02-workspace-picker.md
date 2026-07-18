# T09 Step 02 — Runner/workspace picker and execution-mode badge

Depends on step 01 and the T10 step 01 create contract. The picker selects an online
runner, one advertised opaque workspace ID, and a policy value. It never sends a raw
local path.

## Selection model

```typescript
export interface RunnerSelection {
  runnerId: string | null;
  workspaceId: string | null;
  policy: "manual" | "assisted" | "auto";
}

export const EMPTY_RUNNER_SELECTION: RunnerSelection = {
  runnerId: null,
  workspaceId: null,
  policy: "manual",
};
```

Changing the runner clears the workspace. A runner is selectable only when online and
when it advertises the chosen agent's resolved harness. A workspace is selectable only
when its capabilities satisfy the session's required surface.

## Picker behavior

Mount the picker in the existing new-session flow rather than creating a second create
screen.

Required states:

- feature off: render nothing and perform no runner fetch;
- loading: non-blocking loading copy;
- no runner: show exact pairing command/help link;
- runner offline: show but disable, with reconnect copy;
- unsupported harness: disable create and name the missing harness;
- no approved workspaces: show `omnigent host add-workspace ...` guidance;
- workspace missing required capabilities: disable it with specific copy;
- valid selection: enable policy selector and create.

Suggested copy for policy values must match the actual T10 step 02 contract. Until
that decision lands, do not claim that auto mode contains or auto-runs arbitrary shell
commands.

## Create payload

For the local-runner branch of session creation:

```typescript
const body = {
  agent_id: agentId,
  runner_id: selection.runnerId,
  workspace_id: selection.workspaceId,
  local_runner_policy: selection.policy,
};
```

Do not include `host_id`, `workspace`, or a value derived from `path_label`. The
existing host-launch/managed-sandbox create paths remain separate and keep their own
fields.

Create-button gating:

```typescript
const localRunnerInvalid =
  selection.runnerId !== null &&
  (selection.workspaceId === null || !harnessSupported || !workspaceSupported);
```

The server remains authoritative and must repeat ownership, liveness, workspace, and
harness validation.

## Badge

Use persisted snapshot labels, not client selection state:

```typescript
const mode = labels["omnigent.execution_mode"];
const workspace = labels["omnigent.workspace_label"];
const policy = labels["omnigent.local_runner_policy"];
```

Render a local-runner badge only when `mode === "local_runner"`. The tooltip may show
the display label and policy, but must not expose a local absolute root. A refresh or a
second browser must reconstruct the same badge solely from the session snapshot.

## Tests

Component tests:

- hidden and no fetch when the feature is off;
- pairing instructions when no runner is available;
- changing runner clears workspace;
- offline runner and unsupported harness disable create;
- workspace capability mismatch is specific;
- create payload contains `runner_id`, `workspace_id`, and policy only;
- payload never contains `host_id` or `workspace` in local-runner mode;
- policy copy matches the T10 shell decision;
- badge is reconstructed from labels after remount.

Route/E2E follow-through:

- owner creates a session from the picker;
- foreign runner/workspace selection is rejected server-side;
- raw path injection is rejected;
- created header shows the persisted workspace label after refresh.

## Done when

A user can create a local-runner session from opaque identifiers end to end, and no
browser/server request in this mode carries the local workspace's absolute path.
