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
  const body = (await response.json()) as { data?: unknown[] };
  if (!Array.isArray(body.data)) return [];
  return body.data.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const runner = entry as Record<string, unknown>;
    if (typeof runner.runner_id !== "string" || typeof runner.online !== "boolean") return [];
    const workspaces = Array.isArray(runner.workspaces) ? runner.workspaces : [];
    return [
      {
        runner_id: runner.runner_id,
        online: runner.online,
        runner_version: typeof runner.runner_version === "string" ? runner.runner_version : null,
        os: typeof runner.os === "string" ? runner.os : null,
        arch: typeof runner.arch === "string" ? runner.arch : null,
        harnesses: Array.isArray(runner.harnesses)
          ? runner.harnesses.filter((value): value is string => typeof value === "string")
          : [],
        terminal_transports: Array.isArray(runner.terminal_transports)
          ? runner.terminal_transports.filter((value): value is string => typeof value === "string")
          : [],
        tool_capabilities: Array.isArray(runner.tool_capabilities)
          ? runner.tool_capabilities.filter((value): value is string => typeof value === "string")
          : [],
        workspaces: workspaces.flatMap((value) => {
          if (!value || typeof value !== "object") return [];
          const workspace = value as Record<string, unknown>;
          if (typeof workspace.workspace_id !== "string") return [];
          return [
            {
              workspace_id: workspace.workspace_id,
              display_name:
                typeof workspace.display_name === "string" ? workspace.display_name : null,
              path_label: typeof workspace.path_label === "string" ? workspace.path_label : null,
              capabilities: Array.isArray(workspace.capabilities)
                ? workspace.capabilities.filter(
                    (capability): capability is string => typeof capability === "string",
                  )
                : [],
            },
          ];
        }),
      },
    ];
  });
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
