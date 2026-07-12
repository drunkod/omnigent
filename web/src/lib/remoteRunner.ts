import type { TerminalUiState } from "@/lib/events";
import { authenticatedFetch } from "@/lib/identity";

export interface RemoteHost {
  host_id: string;
  name: string;
  owner: string;
  status: "online" | "offline";
  sandbox_provider?: string | null;
  configured_harnesses?: Record<string, boolean | string> | null;
}

export interface RunnerWorkspace {
  workspace_id: string;
  display_name?: string | null;
  path_label?: string | null;
  capabilities: string[];
}

export interface LocalRunnerSummary {
  runner_id: string;
  online: boolean;
  runner_version?: string | null;
  os?: string | null;
  arch?: string | null;
  harnesses: string[];
  terminal_transports: string[];
  tool_capabilities: string[];
  workspaces: RunnerWorkspace[];
}

export async function fetchHosts(): Promise<RemoteHost[]> {
  const response = await authenticatedFetch("/v1/hosts");
  if (!response.ok) throw new Error(`hosts fetch failed: ${response.status}`);
  const body = (await response.json()) as { hosts?: RemoteHost[]; data?: RemoteHost[] };
  return body.hosts ?? body.data ?? [];
}

export async function fetchLocalRunners(): Promise<LocalRunnerSummary[]> {
  const response = await authenticatedFetch("/v1/runners");
  if (!response.ok) throw new Error(`runner discovery failed: ${response.status}`);
  const body = (await response.json()) as { data?: LocalRunnerSummary[] };
  return body.data ?? [];
}

export async function remoteLocalRunnerEnabled(): Promise<boolean> {
  const response = await authenticatedFetch("/v1/info");
  if (!response.ok) return false;
  const info = (await response.json()) as { remote_local_runner?: boolean };
  return info.remote_local_runner === true;
}

export type AttachLifecycleState = Extract<
  TerminalUiState,
  "runner_offline" | "terminal_exited" | "terminal_detached"
>;

/** T06 attach close-code contract. */
export const ATTACH_CLOSE = {
  RUNNER_OFFLINE: 4503,
  TERMINAL_NOT_FOUND: 4404,
  TERMINAL_DETACHED: 4405,
  TRANSPORT_UNSUPPORTED: 4406,
} as const;

export function stateFromAttachClose(code: number): AttachLifecycleState | null {
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
