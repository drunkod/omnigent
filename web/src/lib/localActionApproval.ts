export type LocalActionKind = "write_file" | "run_shell";
export type LocalActionPolicyMode = "manual" | "assisted" | "auto";
export type ShellGuarantee = "strict_workspace" | "trusted_machine";

/**
 * Bounded, transient approval detail for runner-local actions.
 *
 * This object is deliberately separate from persisted audit entities. The
 * browser never reconstructs missing fields from `content_preview` or free-form
 * messages.
 */
export interface LocalActionApproval {
  version: 1;
  actionId?: string;
  kind: LocalActionKind;
  policyMode: LocalActionPolicyMode;
  workspaceLabel?: string;
  cwd?: string;
  pathSummary: string[];
  commandPreview?: string;
  diffPreview?: string;
  diffTruncated: boolean;
  riskFlags: string[];
  shellGuarantee?: ShellGuarantee;
  expiresAt?: number;
}

const MAX_ACTION_ID = 128;
const MAX_WORKSPACE_LABEL = 256;
const MAX_CWD = 512;
const MAX_PATHS = 16;
const MAX_PATH = 512;
const MAX_COMMAND_PREVIEW = 2_000;
const MAX_DIFF_PREVIEW = 64 * 1024;
const MAX_RISK_FLAGS = 16;
const MAX_RISK_FLAG = 128;

function boundedString(
  value: unknown,
  maxLength: number,
  requireNonEmpty = false,
): string | undefined {
  if (typeof value !== "string") return undefined;
  if (requireNonEmpty && value.length === 0) return undefined;
  if (value.length > maxLength) return undefined;
  return value;
}

function boundedStringArray(value: unknown, maxItems: number, maxLength: number): string[] {
  if (!Array.isArray(value) || value.length > maxItems) return [];
  const parsed: string[] = [];
  for (const item of value) {
    const text = boundedString(item, maxLength, true);
    if (text === undefined) return [];
    parsed.push(text);
  }
  return parsed;
}

function workspaceRelative(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  if (value.startsWith("/") || value.startsWith("\\") || /^[A-Za-z]:[\\/]/.test(value)) {
    return undefined;
  }
  return value;
}

/** Parse one snake_case wire payload into the browser contract. */
export function parseLocalActionApproval(raw: unknown): LocalActionApproval | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;
  if (source.version !== 1) return null;
  if (source.kind !== "write_file" && source.kind !== "run_shell") return null;
  if (
    source.policy_mode !== "manual" &&
    source.policy_mode !== "assisted" &&
    source.policy_mode !== "auto"
  ) {
    return null;
  }

  const actionId = boundedString(source.action_id, MAX_ACTION_ID, true);
  const workspaceLabel = boundedString(source.workspace_label, MAX_WORKSPACE_LABEL, true);
  const cwd = workspaceRelative(boundedString(source.cwd, MAX_CWD, true));
  const commandPreview = boundedString(source.command_preview, MAX_COMMAND_PREVIEW);
  const diffPreview = boundedString(source.diff_preview, MAX_DIFF_PREVIEW);
  const pathSummary = boundedStringArray(source.path_summary, MAX_PATHS, MAX_PATH);
  const riskFlags = boundedStringArray(source.risk_flags, MAX_RISK_FLAGS, MAX_RISK_FLAG);
  const shellGuarantee =
    source.shell_guarantee === "strict_workspace" || source.shell_guarantee === "trusted_machine"
      ? source.shell_guarantee
      : undefined;
  const expiresAt =
    typeof source.expires_at === "number" &&
    Number.isFinite(source.expires_at) &&
    source.expires_at > 0
      ? source.expires_at
      : undefined;

  return {
    version: 1,
    kind: source.kind,
    policyMode: source.policy_mode,
    pathSummary,
    diffTruncated: source.diff_truncated === true,
    riskFlags,
    ...(actionId !== undefined ? { actionId } : {}),
    ...(workspaceLabel !== undefined ? { workspaceLabel } : {}),
    ...(cwd !== undefined ? { cwd } : {}),
    ...(commandPreview !== undefined ? { commandPreview } : {}),
    ...(diffPreview !== undefined ? { diffPreview } : {}),
    ...(shellGuarantee !== undefined ? { shellGuarantee } : {}),
    ...(expiresAt !== undefined ? { expiresAt } : {}),
  };
}
