from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one literal match, found {count}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match for {pattern!r}, found {count}")
    write(path, updated)


LOCAL_ACTION_TS = r'''export type LocalActionKind = "write_file" | "run_shell";
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

function boundedString(value: unknown, maxLength: number, requireNonEmpty = false): string | undefined {
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
'''
write("web/src/lib/localActionApproval.ts", LOCAL_ACTION_TS)

LOCAL_ACTION_COMPONENT = r'''import { CopyIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { LocalActionApproval } from "@/lib/localActionApproval";

const STRICT_GUARANTEE =
  "Strict workspace sandbox: only the selected workspace is writable and the runner denies network and additional mounts by default.";
const TRUSTED_GUARANTEE =
  "Trusted-machine shell: the selected workspace sets the starting directory, but an approved command runs with the runner user's normal machine access.";
const UNKNOWN_GUARANTEE =
  "Shell isolation was not reported. Treat this approval as trusted-machine access and review the command before continuing.";
const STALE_WRITE_WARNING =
  "The write is checked again immediately before execution. If the target changes while this approval is pending, the write will fail and require a new review.";

function CopyPreviewButton({ value, label }: { value: string; label: string }) {
  const copy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(value);
    }
  };
  return (
    <Button size="sm" variant="ghost" type="button" onClick={copy} aria-label={label}>
      <CopyIcon className="mr-1 size-3.5" />
      Copy
    </Button>
  );
}

function SharedMetadata({ approval }: { approval: LocalActionApproval }) {
  return (
    <div className="flex flex-col gap-1 text-xs">
      {approval.workspaceLabel && (
        <span>
          <span className="text-muted-foreground">Workspace: </span>
          {approval.workspaceLabel}
        </span>
      )}
      <span>
        <span className="text-muted-foreground">Policy: </span>
        {approval.policyMode}
      </span>
      {approval.riskFlags.length > 0 && (
        <div aria-label="Risk flags">
          <span className="text-muted-foreground">Risks: </span>
          {approval.riskFlags.join(", ")}
        </div>
      )}
    </div>
  );
}

function ShellApprovalDetails({ approval }: { approval: LocalActionApproval }) {
  const guarantee =
    approval.shellGuarantee === "strict_workspace"
      ? STRICT_GUARANTEE
      : approval.shellGuarantee === "trusted_machine"
        ? TRUSTED_GUARANTEE
        : UNKNOWN_GUARANTEE;
  return (
    <div className="flex flex-col gap-2">
      <SharedMetadata approval={approval} />
      {approval.cwd && (
        <span className="text-xs">
          cwd: <code className="rounded bg-muted px-1 py-0.5 font-mono">{approval.cwd}</code>
        </span>
      )}
      <p className="text-xs" data-testid="shell-guarantee">
        {guarantee}
      </p>
      {approval.commandPreview !== undefined ? (
        <div className="flex flex-col gap-1">
          <pre
            aria-label="Command preview"
            className="max-h-64 overflow-auto rounded bg-muted px-2 py-1 font-mono text-xs whitespace-pre-wrap break-words"
          >
            {approval.commandPreview}
          </pre>
          <div>
            <CopyPreviewButton value={approval.commandPreview} label="Copy command preview" />
          </div>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">Command preview unavailable.</span>
      )}
    </div>
  );
}

function WriteApprovalDetails({ approval }: { approval: LocalActionApproval }) {
  return (
    <div className="flex flex-col gap-2">
      <SharedMetadata approval={approval} />
      {approval.pathSummary.length > 0 ? (
        <ul className="list-disc pl-5 text-xs" aria-label="Affected paths">
          {approval.pathSummary.map((path) => (
            <li key={path}>
              <code className="font-mono">{path}</code>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-xs text-muted-foreground">Affected path unavailable.</span>
      )}
      {approval.diffPreview !== undefined ? (
        <div className="flex flex-col gap-1">
          <pre
            aria-label="Diff preview"
            className="max-h-80 overflow-auto rounded bg-muted px-2 py-1 font-mono text-xs whitespace-pre"
          >
            {approval.diffPreview}
          </pre>
          {approval.diffTruncated && (
            <span className="text-xs font-medium">Diff preview was truncated.</span>
          )}
          <div>
            <CopyPreviewButton value={approval.diffPreview} label="Copy diff preview" />
          </div>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">Diff preview unavailable.</span>
      )}
      <p className="text-xs">{STALE_WRITE_WARNING}</p>
    </div>
  );
}

export function LocalActionApprovalDetails({ approval }: { approval: LocalActionApproval }) {
  return approval.kind === "run_shell" ? (
    <ShellApprovalDetails approval={approval} />
  ) : (
    <WriteApprovalDetails approval={approval} />
  );
}
'''
write("web/src/components/blocks/LocalActionApprovalCard.tsx", LOCAL_ACTION_COMPONENT)

# Shared TypeScript contract imports and inline type replacement.
for path in ("web/src/lib/events.ts", "web/src/lib/blocks.ts", "web/src/lib/renderItems.ts"):
    text = read(path)
    if 'import type { LocalActionApproval } from "./localActionApproval";' not in text:
        text = 'import type { LocalActionApproval } from "./localActionApproval";\n' + text
    pattern = (
        r"  localAction\?: \{\n"
        r"\s*kind: \"read_file\" \| \"write_file\" \| \"list_dir\" \| \"run_shell\" \| \"apply_patch\";\n"
        r"\s*policyMode: \"manual\" \| \"assisted\" \| \"auto\";\n"
        r"\s*\} \| null;"
    )
    text, count = re.subn(pattern, "  localAction?: LocalActionApproval | null;", text, count=1)
    if count != 1:
        raise RuntimeError(f"{path}: localAction inline type replacement count={count}")
    write(path, text)

# SSE parser: consume only bounded typed fields, with a legacy top-level adapter.
sse_path = "web/src/lib/sse.ts"
sse = read(sse_path)
if 'from "./localActionApproval"' not in sse:
    sse = sse.replace(
        'import { NATIVE_TOOL_TYPES } from "./events";\n',
        'import { NATIVE_TOOL_TYPES } from "./events";\nimport { parseLocalActionApproval } from "./localActionApproval";\n',
        1,
    )
legacy_block = re.compile(
    r"    const localActionKind = p\.kind;\n"
    r"    const localActionPolicyMode = p\.policy_mode;\n"
    r"    const localAction: ElicitationRequest\[\"localAction\"\] =\n"
    r".*?"
    r"    const rememberScope: RememberScope \| null =",
    re.S,
)
replacement = '''    const localActionWirePresent =
      p.local_action !== undefined ||
      p.kind === "read_file" ||
      p.kind === "write_file" ||
      p.kind === "list_dir" ||
      p.kind === "run_shell" ||
      p.kind === "apply_patch";
    const legacyLocalAction = {
      version: 1,
      action_id: p.action_id,
      kind: p.kind,
      policy_mode: p.policy_mode,
      workspace_label: p.workspace_label,
      cwd: p.cwd,
      path_summary: p.path_summary,
      command_preview: p.command_preview,
      diff_preview: p.diff_preview,
      diff_truncated: p.diff_truncated,
      risk_flags: p.risk_flags,
      shell_guarantee: p.shell_guarantee,
      expires_at: p.expires_at,
    };
    const localAction = parseLocalActionApproval(p.local_action ?? legacyLocalAction);
    const rememberScope: RememberScope | null ='''
sse, count = legacy_block.subn(replacement, sse, count=1)
if count != 1:
    raise RuntimeError(f"{sse_path}: legacy localAction parser replacement count={count}")
sse = sse.replace(
    '      message: String(p.message ?? ""),\n',
    '      message:\n        localActionWirePresent && localAction === null\n          ? "Unsupported local action approval."\n          : String(p.message ?? ""),\n',
    1,
)
sse = sse.replace(
    '      contentPreview: String(p.content_preview ?? ""),\n',
    '      contentPreview: localActionWirePresent ? "" : String(p.content_preview ?? ""),\n',
    1,
)
write(sse_path, sse)

# Approval card integration.
approval_path = "web/src/components/blocks/ApprovalCard.tsx"
approval = read(approval_path)
if 'import type { LocalActionApproval } from "@/lib/localActionApproval";' not in approval:
    approval = approval.replace(
        'import { formatPreview } from "@/lib/previewFormat";\n',
        'import type { LocalActionApproval } from "@/lib/localActionApproval";\nimport { formatPreview } from "@/lib/previewFormat";\n',
        1,
    )
if 'from "./LocalActionApprovalCard"' not in approval:
    approval = approval.replace(
        'import { ExitPlanModeReview } from "./ExitPlanModeReview";\n',
        'import { ExitPlanModeReview } from "./ExitPlanModeReview";\nimport { LocalActionApprovalDetails } from "./LocalActionApprovalCard";\n',
        1,
    )
approval, count = re.subn(
    r"  localAction\?: \{\n"
    r"\s*kind: \"read_file\" \| \"write_file\" \| \"list_dir\" \| \"run_shell\" \| \"apply_patch\";\n"
    r"\s*policyMode: \"manual\" \| \"assisted\" \| \"auto\";\n"
    r"\s*\} \| null;",
    "  localAction?: LocalActionApproval | null;",
    approval,
    count=1,
)
if count != 1:
    raise RuntimeError(f"{approval_path}: prop localAction replacement count={count}")
approval, count = re.subn(
    r"  const localActionLabel = localAction\n"
    r"    \? \{.*?\}\[localAction\.kind\]\n"
    r"    : null;",
    '''  const localActionLabel =
    localAction?.kind === "write_file"
      ? "Write file"
      : localAction?.kind === "run_shell"
        ? "Run shell command"
        : null;''',
    approval,
    count=1,
    flags=re.S,
)
if count != 1:
    raise RuntimeError(f"{approval_path}: label map replacement count={count}")
approval = approval.replace(
    '''          ) : (
            <span>{message}</span>
          )}''',
    '''          ) : localAction ? (
            <span>{localActionLabel} request resolved.</span>
          ) : (
            <span>{message}</span>
          )}''',
    1,
)
approval = approval.replace(
    '''            <span>{localActionLabel ? `${localActionLabel} requires approval.` : message}</span>
            {localAction && (
              <span className="text-xs text-muted-foreground">
                Policy: {localAction.policyMode}
              </span>
            )}''',
    '''            <span>{localActionLabel ? `${localActionLabel} requires approval.` : message}</span>
            {localAction && <LocalActionApprovalDetails approval={localAction} />}''',
    1,
)
write(approval_path, approval)

# Runner: provide bounded safe previews and explicit shell guarantee to the
# existing approval callback. The server normalizes those legacy top-level
# extras into the nested wire object.
runner_path = "omnigent/runner/local_actions.py"
runner = read(runner_path)
runner = runner.replace("import os\n", "import os\nimport shlex\n", 1)
runner = runner.replace(
    "_SHELL_TIMEOUT_S = 600.0\n",
    "_SHELL_TIMEOUT_S = 600.0\n_MAX_DIFF_PREVIEW_CHARS = 64_000\n_MAX_COMMAND_PREVIEW_CHARS = 2_000\n",
    1,
)
subprocess_marker = '''def subprocess_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the allowlisted environment for local shell actions.
'''
if subprocess_marker not in runner:
    raise RuntimeError("runner local_actions: subprocess_env marker missing")
helper = '''def safe_shell_command_preview(command: str) -> str:
    """Return a bounded command summary that never includes arguments.

    Shell arguments commonly contain tokens, headers, inline environment
    values, or private paths. The approval card therefore shows only the
    executable basename and an explicit hidden-arguments marker.
    """

    try:
        parts = shlex.split(command)
    except ValueError:
        return "Command preview unavailable (unparseable input)."
    if not parts:
        return "Command preview unavailable."
    executable = Path(parts[0]).name or "command"
    preview = executable if len(parts) == 1 else f"{executable} [arguments hidden]"
    return preview[:_MAX_COMMAND_PREVIEW_CHARS]


'''
runner = runner.replace(subprocess_marker, helper + subprocess_marker, 1)
runner = runner.replace(
    "        await self._gate(record, verdict, diff_preview=diff_preview[:64_000])\n",
    '''        await self._gate(
            record,
            verdict,
            diff_preview=diff_preview[:_MAX_DIFF_PREVIEW_CHARS],
            diff_truncated=len(diff_preview) > _MAX_DIFF_PREVIEW_CHARS,
        )
''',
    1,
)
runner = runner.replace(
    '        await self._gate(record, classify_action("run_shell", mode=mode, command=command, cwd=cwd))\n',
    '''        await self._gate(
            record,
            classify_action("run_shell", mode=mode, command=command, cwd=cwd),
            command_preview=safe_shell_command_preview(command),
            shell_guarantee="strict_workspace" if self._strict_shell else "trusted_machine",
        )
''',
    1,
)
write(runner_path, runner)

# Server schema: strict nested model plus normalization from the current runner
# extras. Previews are bounded here before snapshots or SSE serialization.
schema_path = "omnigent/server/schemas.py"
schema = read(schema_path)
schema = schema.replace("import re\n", "import math\nimport re\n", 1)
model_code = r'''

class LocalActionApprovalParams(BaseModel):
    """Bounded transient UI detail for a runner-local approval."""

    version: Literal[1] = 1
    action_id: str | None = Field(default=None, max_length=128)
    kind: Literal["write_file", "run_shell"]
    policy_mode: Literal["manual", "assisted", "auto"]
    workspace_label: str | None = Field(default=None, max_length=256)
    cwd: str | None = Field(default=None, max_length=512)
    path_summary: list[str] = Field(default_factory=list, max_length=16)
    command_preview: str | None = Field(default=None, max_length=2_000)
    diff_preview: str | None = Field(default=None, max_length=64 * 1024)
    diff_truncated: bool = False
    risk_flags: list[str] = Field(default_factory=list, max_length=16)
    shell_guarantee: Literal["strict_workspace", "trusted_machine"] | None = None
    expires_at: float | None = None

    model_config = ConfigDict(extra="forbid")


def _bounded_optional_text(value: Any, limit: int, *, nonempty: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    if nonempty and not value:
        return None
    return value[:limit]


def _bounded_text_list(value: Any, *, count: int, length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:count]:
        if not isinstance(item, str) or not item:
            continue
        result.append(item[:length])
    return result


def _workspace_relative_display(value: Any) -> str | None:
    candidate = _bounded_optional_text(value, 512, nonempty=True)
    if candidate is None:
        return None
    if candidate.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", candidate):
        return None
    return candidate


def _normalize_local_action_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return None
    kind = raw.get("kind")
    policy_mode = raw.get("policy_mode")
    if kind not in {"write_file", "run_shell"}:
        return None
    if policy_mode not in {"manual", "assisted", "auto"}:
        return None

    diff_source = raw.get("diff_preview")
    diff_preview = _bounded_optional_text(diff_source, 64 * 1024)
    diff_truncated = raw.get("diff_truncated") is True
    if isinstance(diff_source, str) and len(diff_source) > 64 * 1024:
        diff_truncated = True

    expires_at = raw.get("expires_at")
    normalized_expires = (
        float(expires_at)
        if isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and math.isfinite(float(expires_at))
        and float(expires_at) > 0
        else None
    )
    shell_guarantee = raw.get("shell_guarantee")
    if shell_guarantee not in {"strict_workspace", "trusted_machine"}:
        shell_guarantee = None

    result: dict[str, Any] = {
        "version": 1,
        "kind": kind,
        "policy_mode": policy_mode,
        "path_summary": _bounded_text_list(raw.get("path_summary"), count=16, length=512),
        "diff_truncated": diff_truncated,
        "risk_flags": _bounded_text_list(raw.get("risk_flags"), count=16, length=128),
    }
    optional_values = {
        "action_id": _bounded_optional_text(raw.get("action_id"), 128, nonempty=True),
        "workspace_label": _bounded_optional_text(
            raw.get("workspace_label"), 256, nonempty=True
        ),
        "cwd": _workspace_relative_display(raw.get("cwd")),
        "command_preview": _bounded_optional_text(raw.get("command_preview"), 2_000),
        "diff_preview": diff_preview,
        "shell_guarantee": shell_guarantee,
        "expires_at": normalized_expires,
    }
    result.update({key: value for key, value in optional_values.items() if value is not None})
    return result
'''
if "class LocalActionApprovalParams" not in schema:
    schema = schema.replace("\nclass ElicitationRequestParams(BaseModel):", model_code + "\n\nclass ElicitationRequestParams(BaseModel):", 1)
field_marker = "    target_session_id: str | None = None\n"
validator_code = r'''    target_session_id: str | None = None
    local_action: LocalActionApprovalParams | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_local_action(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        raw_local_action = data.get("local_action")
        legacy_kind = data.get("kind")
        local_kind = (
            raw_local_action.get("kind")
            if isinstance(raw_local_action, dict)
            else legacy_kind
        )
        is_local_action = local_kind in {
            "read_file",
            "write_file",
            "list_dir",
            "run_shell",
            "apply_patch",
        }
        if raw_local_action is None and is_local_action:
            raw_local_action = {
                "version": 1,
                "action_id": data.get("action_id"),
                "kind": legacy_kind,
                "policy_mode": data.get("policy_mode"),
                "workspace_label": data.get("workspace_label"),
                "cwd": data.get("cwd"),
                "path_summary": data.get("path_summary"),
                "command_preview": data.get("command_preview"),
                "diff_preview": data.get("diff_preview"),
                "diff_truncated": data.get("diff_truncated"),
                "risk_flags": data.get("risk_flags"),
                "shell_guarantee": data.get("shell_guarantee"),
                "expires_at": data.get("expires_at"),
            }
        normalized = _normalize_local_action_payload(raw_local_action)
        if normalized is not None:
            data["local_action"] = normalized
            for key in (
                "action_id",
                "kind",
                "policy_mode",
                "workspace_label",
                "cwd",
                "path_summary",
                "command_preview",
                "diff_preview",
                "diff_truncated",
                "risk_flags",
                "shell_guarantee",
                "expires_at",
            ):
                data.pop(key, None)
        elif is_local_action or raw_local_action is not None:
            # Unsupported/malformed local actions remain resolvable only as a
            # conservative generic prompt; never retain producer previews.
            data["local_action"] = None
            data["message"] = "Approval required for an unsupported local action."
            data["content_preview"] = None
            for key in (
                "command_preview",
                "diff_preview",
                "path_summary",
                "risk_flags",
                "workspace_label",
                "cwd",
            ):
                data.pop(key, None)
        return data
'''
if field_marker not in schema:
    raise RuntimeError("server schema: target_session_id marker missing")
schema = schema.replace(field_marker, validator_code, 1)
write(schema_path, schema)

# Focused parser tests.
write(
    "web/src/lib/localActionApproval.test.ts",
    r'''import { describe, expect, it } from "vitest";
import { parseLocalActionApproval } from "./localActionApproval";

describe("parseLocalActionApproval", () => {
  it("normalizes a valid write payload", () => {
    expect(
      parseLocalActionApproval({
        version: 1,
        action_id: "act_1",
        kind: "write_file",
        policy_mode: "manual",
        workspace_label: "project",
        path_summary: ["src/app.ts"],
        diff_preview: "--- a/src/app.ts\n+++ b/src/app.ts",
        diff_truncated: false,
        risk_flags: ["writes_files"],
      }),
    ).toEqual({
      version: 1,
      actionId: "act_1",
      kind: "write_file",
      policyMode: "manual",
      workspaceLabel: "project",
      pathSummary: ["src/app.ts"],
      diffPreview: "--- a/src/app.ts\n+++ b/src/app.ts",
      diffTruncated: false,
      riskFlags: ["writes_files"],
    });
  });

  it("carries an explicit shell guarantee", () => {
    const parsed = parseLocalActionApproval({
      version: 1,
      kind: "run_shell",
      policy_mode: "assisted",
      path_summary: [],
      command_preview: "pytest [arguments hidden]",
      diff_truncated: false,
      risk_flags: ["shell"],
      shell_guarantee: "strict_workspace",
    });
    expect(parsed?.shellGuarantee).toBe("strict_workspace");
  });

  it("rejects apply_patch and invalid policy modes", () => {
    expect(
      parseLocalActionApproval({ version: 1, kind: "apply_patch", policy_mode: "manual" }),
    ).toBeNull();
    expect(
      parseLocalActionApproval({ version: 1, kind: "write_file", policy_mode: "unsafe" }),
    ).toBeNull();
  });

  it("drops malformed optional fields without recovering raw content", () => {
    const parsed = parseLocalActionApproval({
      version: 1,
      kind: "run_shell",
      policy_mode: "manual",
      cwd: "/absolute/private/path",
      command_preview: "x".repeat(2_001),
      path_summary: ["ok", 42],
      diff_truncated: false,
      risk_flags: ["shell"],
    });
    expect(parsed).not.toBeNull();
    expect(parsed?.cwd).toBeUndefined();
    expect(parsed?.commandPreview).toBeUndefined();
    expect(parsed?.pathSummary).toEqual([]);
  });
});
''',
)

write(
    "web/src/components/blocks/LocalActionApprovalCard.test.tsx",
    r'''import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

afterEach(cleanup);

const base = {
  elicitationId: "elic_local",
  phase: "tool_call",
  policyName: "local_runner",
  requestedSchema: {},
  status: "pending" as const,
  response: null,
};

describe("local-action approval cards", () => {
  it("renders strict shell guarantees without raw producer content", () => {
    const secret = "Bearer secret-that-must-not-render";
    render(
      <ApprovalCard
        {...base}
        message={`raw ${secret}`}
        contentPreview={`raw preview ${secret}`}
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          workspaceLabel: "project",
          cwd: "src",
          pathSummary: [],
          commandPreview: "pytest [arguments hidden]",
          diffTruncated: false,
          riskFlags: ["shell"],
          shellGuarantee: "strict_workspace",
        }}
      />,
    );
    expect(screen.getByText(/Strict workspace sandbox/)).toBeDefined();
    expect(screen.queryByText(/Trusted-machine shell/)).toBeNull();
    expect(screen.getByLabelText("Command preview").textContent).toContain(
      "pytest [arguments hidden]",
    );
    expect(screen.queryByText(secret)).toBeNull();
  });

  it("renders trusted and unknown shell copy conservatively", () => {
    const { rerender } = render(
      <ApprovalCard
        {...base}
        message="shell"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          pathSummary: [],
          diffTruncated: false,
          riskFlags: [],
          shellGuarantee: "trusted_machine",
        }}
      />,
    );
    expect(screen.getByText(/Trusted-machine shell/)).toBeDefined();
    rerender(
      <ApprovalCard
        {...base}
        message="shell"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          pathSummary: [],
          diffTruncated: false,
          riskFlags: [],
        }}
      />,
    );
    expect(screen.getByText(/Shell isolation was not reported/)).toBeDefined();
    expect(screen.getByText(/Command preview unavailable/)).toBeDefined();
  });

  it("renders write diff, truncation, paths, and stale-review warning", () => {
    render(
      <ApprovalCard
        {...base}
        message="write"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "write_file",
          policyMode: "assisted",
          pathSummary: ["src/app.ts"],
          diffPreview: "--- a/src/app.ts\n+++ b/src/app.ts",
          diffTruncated: true,
          riskFlags: ["writes_files"],
        }}
      />,
    );
    expect(screen.getByText("src/app.ts")).toBeDefined();
    expect(screen.getByLabelText("Diff preview")).toBeDefined();
    expect(screen.getByText(/Diff preview was truncated/)).toBeDefined();
    expect(screen.getByText(/checked again immediately before execution/)).toBeDefined();
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDefined();
  });
});
''',
)

# Python schema and side-effect tests.
write(
    "tests/test_t11_local_action_schema.py",
    r'''from omnigent.server.schemas import ElicitationRequestParams


def test_legacy_local_action_extras_normalize_to_bounded_nested_payload() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "approve",
            "kind": "write_file",
            "policy_mode": "manual",
            "path_summary": ["src/app.py"],
            "diff_preview": "x" * (64 * 1024 + 10),
            "risk_flags": ["writes_files"],
        }
    )
    assert params.local_action is not None
    assert params.local_action.kind == "write_file"
    assert len(params.local_action.diff_preview or "") == 64 * 1024
    assert params.local_action.diff_truncated is True
    dumped = params.model_dump()
    assert "diff_preview" not in dumped
    assert dumped["local_action"]["path_summary"] == ["src/app.py"]


def test_malformed_or_apply_patch_payload_degrades_without_preview() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "apply secret patch",
            "content_preview": "Bearer secret",
            "kind": "apply_patch",
            "policy_mode": "manual",
            "diff_preview": "Bearer secret",
        }
    )
    assert params.local_action is None
    assert params.message == "Approval required for an unsupported local action."
    assert params.content_preview is None
    assert "diff_preview" not in params.model_dump()


def test_shell_preview_requires_explicit_safe_field() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "approve",
            "kind": "run_shell",
            "policy_mode": "manual",
            "command_summary": "curl -H 'Authorization: Bearer secret'",
            "command_preview": "curl [arguments hidden]",
            "risk_flags": ["shell"],
            "shell_guarantee": "trusted_machine",
        }
    )
    assert params.local_action is not None
    assert params.local_action.command_preview == "curl [arguments hidden]"
    assert "secret" not in str(params.local_action.model_dump())
''',
)

write(
    "tests/runner/test_local_action_approval_side_effects.py",
    r'''import asyncio

import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.policies.types import PolicyMode
from omnigent.runner import pending_approvals
from omnigent.runner.local_actions import LocalActionGateway
from omnigent.runner.workspace_registry import WorkspaceRegistry


def _gateway(tmp_path, approve, audits):
    registry = WorkspaceRegistry()
    workspace = registry.add_path(tmp_path)
    gateway = LocalActionGateway(
        workspaces=registry,
        runner_id="runner_test",
        publish_audit=lambda record: audits.append(record.to_event()),
        request_approval=approve,
    )
    return gateway, workspace.workspace_id


@pytest.mark.asyncio
async def test_owner_approval_writes_reviewed_content_once(tmp_path) -> None:
    captured = []
    audits = []

    async def approve(record, **payload):
        captured.append(payload)
        return True

    gateway, workspace_id = _gateway(tmp_path, approve, audits)
    target = tmp_path / "note.txt"
    target.write_text("before\n", encoding="utf-8")
    result = await gateway.write_file(
        session_id="conv_owner",
        workspace_id=workspace_id,
        path="note.txt",
        content="after\n",
        mode=PolicyMode.MANUAL,
    )

    assert target.read_text(encoding="utf-8") == "after\n"
    assert result["bytes_written"] == len("after\n".encode())
    assert captured[0]["diff_preview"].startswith("--- a/note.txt")
    assert captured[0]["diff_truncated"] is False
    assert [event["status"] for event in audits] == ["requested", "approved", "completed"]


@pytest.mark.asyncio
async def test_denied_write_leaves_file_unchanged(tmp_path) -> None:
    audits = []

    async def deny(record, **payload):
        return False

    gateway, workspace_id = _gateway(tmp_path, deny, audits)
    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(OmnigentError) as exc_info:
        await gateway.write_file(
            session_id="conv_owner",
            workspace_id=workspace_id,
            path="note.txt",
            content="replacement",
            mode=PolicyMode.MANUAL,
        )
    assert exc_info.value.code == ErrorCode.LOCAL_ACTION_REQUIRES_APPROVAL
    assert target.read_text(encoding="utf-8") == "original"
    assert [event["status"] for event in audits] == ["requested", "denied"]


@pytest.mark.asyncio
async def test_changed_target_conflicts_without_stale_write(tmp_path) -> None:
    audits = []
    target = tmp_path / "note.txt"
    target.write_text("reviewed", encoding="utf-8")

    async def mutate_then_approve(record, **payload):
        target.write_text("newer", encoding="utf-8")
        return True

    gateway, workspace_id = _gateway(tmp_path, mutate_then_approve, audits)
    with pytest.raises(OmnigentError) as exc_info:
        await gateway.write_file(
            session_id="conv_owner",
            workspace_id=workspace_id,
            path="note.txt",
            content="stale replacement",
            mode=PolicyMode.MANUAL,
        )
    assert exc_info.value.code == ErrorCode.CONFLICT
    assert target.read_text(encoding="utf-8") == "newer"
    assert audits[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_denied_shell_never_starts_and_preview_hides_arguments(tmp_path, monkeypatch) -> None:
    captured = []
    audits = []

    async def deny(record, **payload):
        captured.append(payload)
        return False

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("shell process must not start after denial")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", unexpected_spawn)
    gateway, workspace_id = _gateway(tmp_path, deny, audits)
    secret = "Bearer secret-value"
    with pytest.raises(OmnigentError):
        await gateway.run_shell(
            session_id="conv_owner",
            workspace_id=workspace_id,
            command=f'curl -H "Authorization: {secret}" https://example.invalid',
            cwd=".",
            mode=PolicyMode.MANUAL,
        )
    assert captured[0]["command_preview"] == "curl [arguments hidden]"
    assert secret not in str(captured[0])
    assert captured[0]["shell_guarantee"] == "trusted_machine"
    assert [event["status"] for event in audits] == ["requested", "denied"]


@pytest.mark.asyncio
async def test_pending_resolution_is_at_most_once() -> None:
    pending_approvals.reset_for_tests()
    future = pending_approvals.register("elic_once")
    try:
        assert pending_approvals.resolve("elic_once", True) is True
        assert pending_approvals.resolve("elic_once", True) is False
        assert await future is True
    finally:
        pending_approvals.cleanup("elic_once")
        pending_approvals.reset_for_tests()
''',
)

print("T11 source transformations completed")
