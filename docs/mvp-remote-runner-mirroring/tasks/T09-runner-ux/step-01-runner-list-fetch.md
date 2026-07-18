# T09 Step 01 — Canonical runner discovery types and fetch

This step starts only after T10 step 01 lands its owner-scoped discovery contract.
Examples below assume the recommended `GET /v1/runners` projection. If T10 chooses an
enriched `/v1/hosts` response instead, keep the same semantic model and use the exact
landed endpoint.

## Required server response

The web client needs a projection like:

```json
{
  "data": [
    {
      "runner_id": "runner_abc",
      "host_id": "host_optional",
      "display_name": "Workstation",
      "online": true,
      "runner_version": "0.3.0",
      "os": "darwin",
      "arch": "arm64",
      "harnesses": ["codex", "claude-native"],
      "terminal_transports": ["control", "pty"],
      "tool_capabilities": ["read_file", "write_file", "run_shell"],
      "workspaces": [
        {
          "workspace_id": "ws_123",
          "display_name": "omnigent",
          "path_label": "~/src/omnigent",
          "capabilities": ["read", "write", "shell", "git", "terminal"]
        }
      ]
    }
  ]
}
```

Rules:

- owner-scoped server-side;
- `runner_id` is explicit and is the session-create identifier;
- workspaces expose opaque IDs and display labels only;
- no absolute root path, pairing token, or auth material;
- offline runners may remain listed, but cannot be selected for a new session unless
  the create route supports a documented wake/reconnect flow.

## Web types — `web/src/lib/remoteRunner.ts`

```typescript
export interface RunnerWorkspace {
  workspace_id: string;
  display_name: string;
  path_label: string;
  capabilities: string[];
}

export interface LocalRunnerSummary {
  runner_id: string;
  host_id?: string | null;
  display_name?: string | null;
  online: boolean;
  runner_version?: string | null;
  os?: string | null;
  arch?: string | null;
  harnesses: string[];
  terminal_transports: string[];
  tool_capabilities: string[];
  workspaces: RunnerWorkspace[];
}

export async function fetchLocalRunners(): Promise<LocalRunnerSummary[]> {
  const response = await authenticatedFetch("/v1/runners");
  if (!response.ok) {
    throw new Error(`runner discovery failed: ${response.status}`);
  }
  const body = (await response.json()) as { data?: LocalRunnerSummary[] };
  return body.data ?? [];
}

export async function remoteLocalRunnerEnabled(): Promise<boolean> {
  const response = await authenticatedFetch("/v1/info");
  if (!response.ok) return false;
  const info = (await response.json()) as { remote_local_runner?: boolean };
  return info.remote_local_runner === true;
}
```

Do not use the old nested `info.capabilities.remote_local_runner` sketch; the landed
server field is top-level.

## Hook

Follow the existing app data-fetch pattern. Polling is acceptable for alpha if no
push source exists, but it must stop while the capability is off and while the view is
unmounted. Avoid introducing a second global liveness store solely for this picker.

```typescript
export function useLocalRunners(enabled: boolean) {
  // returns { runners: LocalRunnerSummary[] | null, error, refresh }
}
```

## Tests

- returns `data` from the canonical response;
- uses `authenticatedFetch`;
- treats a non-2xx discovery response as an error;
- reads top-level `/v1/info.remote_local_runner`;
- performs no discovery request when the feature is disabled;
- rejects/ignores malformed entries according to the runtime validation approach used
  elsewhere in the web client;
- never models or renders an absolute workspace root.

## Done when

- Types match the exact T10 response.
- One test asserts `runner_id` and `workspace_id` survive fetch unchanged.
- Flag-off mode performs no runner-discovery loop.
- Step 02 can create a request without converting a display label into a path.
