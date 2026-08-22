import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useLocalRunners } from "@/hooks/useLocalRunners";
import type { LocalRunnerSummary } from "@/lib/remoteRunner";

export function runnerDisplayLabel(runner: LocalRunnerSummary, t?: TFunction): string {
  const workspace = runner.workspaces[0];
  const workspaceLabel = workspace?.display_name ?? workspace?.path_label;
  if (workspaceLabel) {
    return `${workspaceLabel} ${t?.("misc.residual.hostCapabilityPanel.runnerSuffix", { defaultValue: "runner" }) ?? "runner"}`;
  }
  return (
    t?.("misc.residual.hostCapabilityPanel.localRunner", { defaultValue: "Local runner" }) ??
    "Local runner"
  );
}

function RunnerCard({ runner }: { runner: LocalRunnerSummary }) {
  const { t } = useTranslation();
  const runnerLabel = runnerDisplayLabel(runner, t);
  const status = runner.online
    ? t("misc.residual.hostCapabilityPanel.online", { defaultValue: "online" })
    : t("misc.residual.hostCapabilityPanel.offline", { defaultValue: "offline" });
  return (
    <section className="rounded border p-3" aria-label={runnerLabel}>
      <header className="flex items-center gap-2">
        <span
          className={`size-2 rounded-full ${runner.online ? "bg-emerald-500" : "bg-muted-foreground"}`}
          aria-label={status}
        />
        <strong>{runnerLabel}</strong>
        <span className="text-xs text-muted-foreground">{status}</span>
      </header>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">
          {t("misc.residual.hostCapabilityPanel.harnesses", { defaultValue: "Harnesses" })}
        </dt>
        <dd>
          {runner.harnesses.length
            ? runner.harnesses.join(", ")
            : t("misc.residual.hostCapabilityPanel.noneReported", {
                defaultValue: "None reported",
              })}
        </dd>
        <dt className="text-muted-foreground">
          {t("misc.residual.hostCapabilityPanel.workspaces", { defaultValue: "Workspaces" })}
        </dt>
        <dd>
          {runner.workspaces.length
            ? runner.workspaces
                .map(
                  (workspace) =>
                    workspace.display_name ?? workspace.path_label ?? workspace.workspace_id,
                )
                .join(", ")
            : t("misc.residual.hostCapabilityPanel.noApprovedWorkspaces", {
                defaultValue: "No approved workspaces",
              })}
        </dd>
        <dt className="text-muted-foreground">
          {t("misc.residual.hostCapabilityPanel.terminal", { defaultValue: "Terminal" })}
        </dt>
        <dd>
          {runner.terminal_transports.join(", ") ||
            t("misc.residual.hostCapabilityPanel.noTransportReported", {
              defaultValue: "No transport reported",
            })}
        </dd>
        <dt className="text-muted-foreground">
          {t("misc.residual.hostCapabilityPanel.tools", { defaultValue: "Tools" })}
        </dt>
        <dd>
          {runner.tool_capabilities.join(", ") ||
            t("misc.residual.hostCapabilityPanel.noGatewayToolsReported", {
              defaultValue: "No gateway tools reported",
            })}
        </dd>
      </dl>
    </section>
  );
}

export function HostCapabilityPanel({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const query = useLocalRunners(enabled);
  if (!enabled) return null;
  if (query.isLoading) {
    return (
      <p>{t("misc.residual.hostCapabilityPanel.loading", { defaultValue: "Loading runners…" })}</p>
    );
  }
  if (query.isError) {
    return (
      <p role="alert">
        {t("misc.residual.hostCapabilityPanel.loadError", {
          defaultValue: "Couldn’t load runners: {{error}}",
          error: String(query.error),
        })}
      </p>
    );
  }
  if (!query.data?.length) {
    return (
      <p>
        {t("misc.residual.hostCapabilityPanel.empty", {
          defaultValue: "No local runners paired. Start a runner on your machine to pair one.",
        })}
      </p>
    );
  }
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      {query.data.map((runner) => (
        <RunnerCard key={runner.runner_id} runner={runner} />
      ))}
    </div>
  );
}
