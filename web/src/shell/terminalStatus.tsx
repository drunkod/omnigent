import { type ConnectionState } from "@/components/blocks/TerminalSession";
import { type TerminalInfo } from "@/hooks/useTerminals";
import { cn } from "@/lib/utils";
import type { RunnerUiState, TerminalPanelState } from "@/store/terminalLifecycleStore";

/**
 * Derived per-terminal status shown in terminal selectors.
 *
 * The terminal resource's ``running`` flag is per-terminal. The live
 * WebSocket bridge state and activity timestamps are only known for
 * mounted terminals.
 */
export type TerminalStatus =
  | "active"
  | "idle"
  | "connecting"
  | "error"
  | "closed"
  | "runner_offline"
  | "reconciling"
  | "relaunching"
  | "exited"
  | "failed"
  | "detached";

export const STATUS_CONFIG: Record<TerminalStatus, { label: string; className: string }> = {
  active: { label: "Active", className: "bg-emerald-500" },
  idle: { label: "Idle", className: "bg-muted-foreground/55" },
  connecting: { label: "Connecting", className: "bg-amber-500 animate-pulse" },
  error: { label: "Error", className: "bg-red-500" },
  closed: { label: "Closed", className: "bg-black dark:bg-white" },
  runner_offline: { label: "Runner offline", className: "bg-amber-500" },
  reconciling: { label: "Checking", className: "bg-sky-500 animate-pulse" },
  relaunching: { label: "Relaunching", className: "bg-amber-500 animate-pulse" },
  exited: { label: "Exited", className: "bg-muted-foreground" },
  failed: { label: "Failed", className: "bg-red-500" },
  detached: { label: "Detached", className: "bg-amber-500" },
};

/**
 * Render a visible status dot and label for a terminal tab or selector row.
 *
 * :param status: Terminal-local display status, e.g. ``"idle"``.
 */
export function TerminalStatusBadge({ status }: { status: TerminalStatus }) {
  const { label, className } = STATUS_CONFIG[status];
  return (
    <span
      aria-label={label}
      title={label}
      className="inline-flex shrink-0 items-center gap-1 text-muted-foreground text-xs"
    >
      <span className={cn("inline-block size-1.5 rounded-full", className)} />
      <span>{label}</span>
    </span>
  );
}

/**
 * Derive the display status for a single terminal.
 *
 * :param terminal: Terminal resource entry from ``useTerminals``.
 * :param connectionState: Live bridge state for this terminal when it is
 *     mounted. Pass ``null`` for inactive terminals.
 * :param isActive: Best-effort activity flag from recent PTY output.
 * :returns: Terminal display status.
 */
export function deriveTerminalStatus(
  terminal: TerminalInfo,
  connectionState: ConnectionState | null,
  isActive = false,
  lifecycle: {
    runnerState: RunnerUiState;
    terminalStateById: Record<string, TerminalPanelState>;
  } | null = null,
): TerminalStatus {
  if (lifecycle?.runnerState === "runner_offline") return "runner_offline";
  if (lifecycle?.runnerState === "runner_reconnected") return "reconciling";
  switch (lifecycle?.terminalStateById[terminal.id]) {
    case "terminal_relaunching":
      return "relaunching";
    case "terminal_exited":
      return "exited";
    case "terminal_failed":
      return "failed";
    case "terminal_detached":
      return "detached";
  }
  if (connectionState?.kind === "closed") return "closed";
  if (connectionState?.kind === "error") return "error";
  if (connectionState?.kind === "connecting") return "connecting";
  if (!terminal.running) return "closed";
  if (isActive) return "active";
  return "idle";
}
