import { useHosts, type Host } from "@/hooks/useHosts";

function HostCard({ host }: { host: Host }) {
  const harnesses = Object.keys(host.configured_harnesses ?? {});
  return (
    <section className="rounded border p-3" aria-label={`Host ${host.host_id}`}>
      <header className="flex items-center gap-2">
        <span
          className={`size-2 rounded-full ${host.status === "online" ? "bg-emerald-500" : "bg-muted-foreground"}`}
          aria-label={host.status}
        />
        <strong>{host.name}</strong>
        <span className="text-xs text-muted-foreground">{host.status}</span>
      </header>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Harnesses</dt>
        <dd>{harnesses.length ? harnesses.join(", ") : "None reported"}</dd>
        <dt className="text-muted-foreground">Runner</dt>
        <dd>{host.configured_harnesses ? "Capabilities reported" : "No capability report"}</dd>
      </dl>
    </section>
  );
}

export function HostCapabilityPanel({ enabled }: { enabled: boolean }) {
  const query = useHosts({ enabled, includeSandbox: true });
  if (!enabled) return null;
  if (query.isLoading) return <p>Loading hosts…</p>;
  if (query.isError) return <p role="alert">Couldn’t load hosts: {String(query.error)}</p>;
  if (!query.data?.length) {
    return <p>No hosts paired. Run `omnigent host` on your machine to pair one.</p>;
  }
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      {query.data.map((host) => (
        <HostCard key={host.host_id} host={host} />
      ))}
    </div>
  );
}
