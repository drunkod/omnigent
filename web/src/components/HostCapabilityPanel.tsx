import { useLocalRunners } from "@/hooks/useLocalRunners";
import type { LocalRunnerSummary } from "@/lib/remoteRunner";

export function runnerDisplayLabel(runner: LocalRunnerSummary): string {
  const workspace = runner.workspaces[0];
  const workspaceLabel = workspace?.display_name ?? workspace?.path_label;
  return workspaceLabel ? `${workspaceLabel} runner` : "Local runner";
}

function RunnerCard({ runner }: { runner: LocalRunnerSummary }) {
  const runnerLabel = runnerDisplayLabel(runner);
  return (
    <section className="rounded border p-3" aria-label={runnerLabel}>
      <header className="flex items-center gap-2">
        <span
          className={`size-2 rounded-full ${runner.online ? "bg-emerald-500" : "bg-muted-foreground"}`}
          aria-label={runner.online ? "online" : "offline"}
        />
        <strong>{runnerLabel}</strong>
        <span className="text-xs text-muted-foreground">
          {runner.online ? "online" : "offline"}
        </span>
      </header>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Harnesses</dt>
        <dd>{runner.harnesses.length ? runner.harnesses.join(", ") : "None reported"}</dd>
        <dt className="text-muted-foreground">Workspaces</dt>
        <dd>
          {runner.workspaces.length
            ? runner.workspaces
                .map(
                  (workspace) =>
                    workspace.display_name ?? workspace.path_label ?? workspace.workspace_id,
                )
                .join(", ")
            : "No approved workspaces"}
        </dd>
        <dt className="text-muted-foreground">Terminal</dt>
        <dd>{runner.terminal_transports.join(", ") || "No transport reported"}</dd>
        <dt className="text-muted-foreground">Tools</dt>
        <dd>{runner.tool_capabilities.join(", ") || "No gateway tools reported"}</dd>
      </dl>
    </section>
  );
}

export function HostCapabilityPanel({ enabled }: { enabled: boolean }) {
  const query = useLocalRunners(enabled);
  if (!enabled) return null;
  if (query.isLoading) return <p>Loading runners…</p>;
  if (query.isError) return <p role="alert">Couldn’t load runners: {String(query.error)}</p>;
  if (!query.data?.length) {
    return <p>No local runners paired. Start a runner on your machine to pair one.</p>;
  }
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      {query.data.map((runner) => (
        <RunnerCard key={runner.runner_id} runner={runner} />
      ))}
    </div>
  );
}
