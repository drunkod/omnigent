# T09 Step 03 — Runner capability dashboard (Deferred D)

Track 2, step 3. Depends on step 01 (`useHosts`). A read-only panel
showing everything a paired host advertises: version, OS/arch, harness
readiness, terminal transports, workspaces, last-seen, reconnect state.
Lands last in the track because it's pure presentation over data steps
01–02 already fetch.

## 1. Panel — `web/src/components/HostCapabilityPanel.tsx`

```tsx
import { useHosts } from "../hooks/useHosts";
import type { HostRunnerInfo } from "../lib/remoteRunner";

function HostCard({ host }: { host: HostRunnerInfo }) {
  return (
    <section className="rounded border p-3" aria-label={`Host ${host.host_id}`}>
      <header className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${host.online ? "bg-green-500" : "bg-gray-400"}`}
          aria-hidden
        />
        <strong>{host.display_name ?? host.host_id}</strong>
        <span className="text-xs opacity-70">
          {host.os}/{host.arch} · {host.runner_version ?? "unknown version"}
        </span>
      </header>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt>Harnesses</dt>
        <dd>{host.harnesses.length ? host.harnesses.join(", ") : "none detected"}</dd>
        <dt>Terminal transports</dt>
        <dd>{host.terminal_transports.join(", ") || "unavailable (tmux missing?)"}</dd>
        <dt>Workspaces</dt>
        <dd>
          <ul>
            {host.workspaces.map((ws) => (
              <li key={ws.workspace_id}>
                {ws.display_name} <span className="opacity-70">({ws.path_label})</span>
              </li>
            ))}
          </ul>
        </dd>
      </dl>
    </section>
  );
}

export function HostCapabilityPanel({ enabled }: { enabled: boolean }) {
  const { hosts, error } = useHosts(enabled);
  if (!enabled) return null;
  if (error) return <p role="alert">Couldn’t load hosts: {error}</p>;
  if (hosts === null) return <p>Loading…</p>;
  if (hosts.length === 0) {
    return (
      <p>
        No hosts paired. Run <code>omnigent host --server {window.location.origin}</code>{" "}
        on your machine to pair one.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {hosts.map((h) => (
        <HostCard key={h.host_id} host={h} />
      ))}
    </div>
  );
}
```

Mount wherever settings/infrastructure panels live (follow the existing
settings-page pattern; there is no dedicated infra page yet — a
"Runners" section in settings is the smallest home).

## 2. Empty/degraded states worth explicit copy

- **Offline host**: keep the card, gray dot, add last-seen when the API
  exposes it (`GET /v1/hosts` — check the probed payload; if absent, file
  a small server follow-up rather than faking it client-side).
- **No terminal transports**: means tmux missing/unsupported platform —
  the copy above says so, matching `detect_terminal_transports`'s
  behavior (runner `capabilities.py`).
- **Harness not installed**: shows in the harness list; the picker
  (step 02) is where the actionable warning lives.

## 3. Tests — `HostCapabilityPanel.test.tsx`

```tsx
it("renders one card per host with harnesses and workspaces", ...);
it("shows pairing instructions when no hosts exist", ...);
it("marks offline hosts with a gray indicator", ...);
it("explains missing terminal transports", ...);
```

## Done when

- Panel reflects a live paired host end-to-end (manual QA with
  `omnigent host`).
- All degraded states render specific copy, not blank sections.
- Track 2 complete: fetch → picker/badge → dashboard.
