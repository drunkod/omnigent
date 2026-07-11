# T09 Step 01 — Runner list types + fetch (Deferred A, corrected)

Track 2, step 1. The original Deferred A sketch assumed `GET /v1/runners`;
the implemented API is **hosts-shaped** (`omnigent/server/routes/hosts.py`):
`GET /v1/hosts` lists paired hosts with their runners/workspaces, scoped to
the owner (`test_list_runners_scoped_to_owner`). Build the web types against
that.

## 1. Probe the real payload first

Before writing types, hit the route once and copy the actual shape —
the sketch below is field-name-guessing from the server models:

```bash
curl -s "$SERVER/v1/hosts" -H "Authorization: Bearer $TOKEN" | jq .
```

## 2. Types + fetch — `web/src/lib/remoteRunner.ts`

```typescript
export interface HostWorkspace {
  workspace_id: string;
  display_name: string;
  path_label: string;
  capabilities?: string[];
}

export interface HostRunnerInfo {
  host_id: string;
  display_name?: string;
  online: boolean;
  os?: string;
  arch?: string;
  runner_version?: string;
  harnesses: string[];
  terminal_transports: string[];
  workspaces: HostWorkspace[];
}

export async function fetchHosts(): Promise<HostRunnerInfo[]> {
  const resp = await fetch("/v1/hosts");
  if (!resp.ok) throw new Error(`hosts fetch failed: ${resp.status}`);
  const body = await resp.json();
  return (body.data ?? body.hosts ?? []) as HostRunnerInfo[];
}

/** Capability gate: hide the whole runner UX unless the server opts in. */
export async function remoteLocalRunnerEnabled(): Promise<boolean> {
  const resp = await fetch("/v1/info");
  if (!resp.ok) return false;
  const info = await resp.json();
  return info?.capabilities?.remote_local_runner === true;
}
```

`remote_local_runner` in `/v1/info` capabilities is live since `95d9988e`
(`omnigent/server/app.py` ~L1849) — the picker must not render when false.

## 3. Hook with polling — `web/src/hooks/useHosts.ts`

```typescript
import { useEffect, useState } from "react";
import { fetchHosts, type HostRunnerInfo } from "../lib/remoteRunner";

const POLL_MS = 15_000;

export function useHosts(enabled: boolean): {
  hosts: HostRunnerInfo[] | null;
  error: string | null;
} {
  const [hosts, setHosts] = useState<HostRunnerInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = () =>
      fetchHosts()
        .then((h) => !cancelled && (setHosts(h), setError(null)))
        .catch((e) => !cancelled && setError(String(e)));
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return { hosts, error };
}
```

## 4. Tests — `web/src/lib/remoteRunner.test.ts`

```typescript
import { describe, expect, it, vi } from "vitest";
import { fetchHosts, remoteLocalRunnerEnabled } from "./remoteRunner";

describe("fetchHosts", () => {
  it("returns data array from the hosts envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: [{ host_id: "h1", online: true,
        harnesses: [], terminal_transports: [], workspaces: [] }] })),
    ));
    const hosts = await fetchHosts();
    expect(hosts).toHaveLength(1);
    expect(hosts[0].host_id).toBe("h1");
  });

  it("throws on non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    await expect(fetchHosts()).rejects.toThrow("hosts fetch failed: 500");
  });
});

describe("remoteLocalRunnerEnabled", () => {
  it("is false when the capability is absent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ capabilities: {} })),
    ));
    expect(await remoteLocalRunnerEnabled()).toBe(false);
  });
});
```

## Done when

- Types match the probed `/v1/hosts` payload (update the sketch fields).
- Capability gate verified against a flag-off server (empty UI, no fetch
  loop).
- Step 02 (picker) can consume `useHosts` without further API work.
