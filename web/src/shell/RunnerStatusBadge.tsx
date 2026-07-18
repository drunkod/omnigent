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
  const lifecycle = useTerminalLifecycleStore(selectRunnerState(conversationId));
  const pollOnline = useSessionRunnerOnline(conversationId);

  if (executionMode !== "local_runner") return null;

  const offline =
    lifecycle === "runner_offline" || (lifecycle === "online" && pollOnline === false);
  const reconnecting = lifecycle === "runner_reconnected";
  const label = offline
    ? "Local runner offline"
    : reconnecting
      ? "Reconnecting local runner"
      : workspaceLabel
        ? `Local · ${workspaceLabel}`
        : "Local runner";
  const title = offline
    ? "Session is preserved while the runner is offline"
    : policyMode
      ? `Local workspace${workspaceLabel ? `: ${workspaceLabel}` : ""} · ${policyMode} permissions`
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
      {offline && (
        <span className="sr-only">
          Session is preserved and will recover when the runner returns.
        </span>
      )}
    </span>
  );
}
