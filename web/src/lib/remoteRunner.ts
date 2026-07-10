import type { TerminalUiState } from "@/lib/events";

/** T06 attach close-code contract. */
export const ATTACH_CLOSE = {
  RUNNER_OFFLINE: 4503,
  TERMINAL_NOT_FOUND: 4404,
  TERMINAL_DETACHED: 4405,
  TRANSPORT_UNSUPPORTED: 4406,
} as const;

export function stateFromAttachClose(code: number): TerminalUiState | null {
  switch (code) {
    case ATTACH_CLOSE.RUNNER_OFFLINE:
      return "runner_offline";
    case ATTACH_CLOSE.TERMINAL_NOT_FOUND:
      return "terminal_exited";
    case ATTACH_CLOSE.TERMINAL_DETACHED:
      return "terminal_detached";
    default:
      return null;
  }
}

export function attachQuery(opts: {
  transports: string[];
  debugOverride?: "control" | "pty";
  readOnly: boolean;
}): string {
  const transport = opts.debugOverride ?? (opts.transports.includes("control") ? "control" : "pty");
  const params = new URLSearchParams({ transport });
  if (opts.readOnly) params.set("read_only", "true");
  return params.toString();
}
