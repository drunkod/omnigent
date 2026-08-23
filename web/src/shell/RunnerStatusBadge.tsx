import { useTranslation } from "react-i18next";
import { useTerminalLifecycleStore, selectRunnerState } from "@/store/terminalLifecycleStore";
import { useSessionRunnerOnline } from "@/hooks/RunnerHealthProvider";

interface RunnerStatusBadgeProps {
  conversationId: string;
  executionMode: string | null | undefined;
  workspaceLabel?: string | null;
  policyMode?: string | null;
}

export function RunnerStatusBadge({
  conversationId,
  executionMode,
  workspaceLabel,
  policyMode,
}: RunnerStatusBadgeProps) {
  const { t } = useTranslation();
  const lifecycle = useTerminalLifecycleStore(selectRunnerState(conversationId));
  const pollOnline = useSessionRunnerOnline(conversationId);

  if (executionMode !== "local_runner") return null;

  const offline =
    lifecycle === "runner_offline" || (lifecycle === "online" && pollOnline === false);
  const reconnecting = lifecycle === "runner_reconnected";
  const label = offline
    ? t("misc.runner.offline")
    : reconnecting
      ? t("misc.runner.reconnecting")
      : workspaceLabel
        ? t("misc.runner.localWorkspace", { workspace: workspaceLabel })
        : t("misc.runner.local");
  const title = offline
    ? t("misc.runner.offlineTitle")
    : policyMode
      ? t("misc.runner.workspacePermissions", {
          workspaceSuffix: workspaceLabel ? `: ${workspaceLabel}` : "",
          policyMode,
        })
      : label;

  return (
    <span
      data-testid="runner-status-badge"
      data-state={offline ? "offline" : reconnecting ? "reconnecting" : "online"}
      className="group inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      title={title}
    >
      <span
        aria-hidden
        className={
          offline
            ? "size-1.5 rounded-full bg-amber-500"
            : reconnecting
              ? "size-1.5 animate-pulse rounded-full bg-sky-500"
              : "size-1.5 rounded-full bg-emerald-500"
        }
      />
      <span>{label}</span>
      {offline && <span className="sr-only">{t("misc.runner.offlineRecovery")}</span>}
    </span>
  );
}
