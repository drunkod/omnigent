import { CopyIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  const copy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(value);
    }
  };
  return (
    <Button size="sm" variant="ghost" type="button" onClick={copy} aria-label={label}>
      <CopyIcon className="mr-1 size-3.5" />
      {t("permissions.approval.localAction.copy", { defaultValue: "Copy" })}
    </Button>
  );
}

function SharedMetadata({ approval }: { approval: LocalActionApproval }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1 text-xs">
      {approval.workspaceLabel && (
        <span>
          <span className="text-muted-foreground">
            {t("permissions.approval.localAction.workspace", { defaultValue: "Workspace:" })}{" "}
          </span>
          {approval.workspaceLabel}
        </span>
      )}
      <span>
        <span className="text-muted-foreground">
          {t("permissions.approval.localAction.policy", { defaultValue: "Policy:" })}{" "}
        </span>
        {approval.policyMode}
      </span>
      {approval.riskFlags.length > 0 && (
        <div
          aria-label={t("permissions.approval.localAction.riskFlags", {
            defaultValue: "Risk flags",
          })}
        >
          <span className="text-muted-foreground">
            {t("permissions.approval.localAction.risks", { defaultValue: "Risks:" })}{" "}
          </span>
          {approval.riskFlags.join(", ")}
        </div>
      )}
    </div>
  );
}

function ShellApprovalDetails({ approval }: { approval: LocalActionApproval }) {
  const { t } = useTranslation();
  const guarantee =
    approval.shellGuarantee === "strict_workspace"
      ? t("permissions.approval.localAction.strictGuarantee", { defaultValue: STRICT_GUARANTEE })
      : approval.shellGuarantee === "trusted_machine"
        ? t("permissions.approval.localAction.trustedGuarantee", {
            defaultValue: TRUSTED_GUARANTEE,
          })
        : t("permissions.approval.localAction.unknownGuarantee", {
            defaultValue: UNKNOWN_GUARANTEE,
          });
  return (
    <div className="flex flex-col gap-2">
      <SharedMetadata approval={approval} />
      {approval.cwd && (
        <span className="text-xs">
          {t("permissions.approval.localAction.cwd", { defaultValue: "cwd:" })}{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono">{approval.cwd}</code>
        </span>
      )}
      <p className="text-xs" data-testid="shell-guarantee">
        {guarantee}
      </p>
      {approval.commandPreview !== undefined ? (
        <div className="flex flex-col gap-1">
          <pre
            aria-label={t("permissions.approval.localAction.commandPreview", {
              defaultValue: "Command preview",
            })}
            className="max-h-64 overflow-auto rounded bg-muted px-2 py-1 font-mono text-xs whitespace-pre-wrap break-words"
          >
            {approval.commandPreview}
          </pre>
          <div>
            <CopyPreviewButton
              value={approval.commandPreview}
              label={t("permissions.approval.localAction.copyCommandPreview", {
                defaultValue: "Copy command preview",
              })}
            />
          </div>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">
          {t("permissions.approval.localAction.commandPreviewUnavailable", {
            defaultValue: "Command preview unavailable.",
          })}
        </span>
      )}
    </div>
  );
}

function WriteApprovalDetails({ approval }: { approval: LocalActionApproval }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2">
      <SharedMetadata approval={approval} />
      {approval.pathSummary.length > 0 ? (
        <ul
          className="list-disc pl-5 text-xs"
          aria-label={t("permissions.approval.localAction.affectedPaths", {
            defaultValue: "Affected paths",
          })}
        >
          {approval.pathSummary.map((path) => (
            <li key={path}>
              <code className="font-mono">{path}</code>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-xs text-muted-foreground">
          {t("permissions.approval.localAction.affectedPathUnavailable", {
            defaultValue: "Affected path unavailable.",
          })}
        </span>
      )}
      {approval.diffPreview !== undefined ? (
        <div className="flex flex-col gap-1">
          <pre
            aria-label={t("permissions.approval.localAction.diffPreview", {
              defaultValue: "Diff preview",
            })}
            className="max-h-80 overflow-auto rounded bg-muted px-2 py-1 font-mono text-xs whitespace-pre"
          >
            {approval.diffPreview}
          </pre>
          {approval.diffTruncated && (
            <span className="text-xs font-medium">
              {t("permissions.approval.localAction.diffPreviewTruncated", {
                defaultValue: "Diff preview was truncated.",
              })}
            </span>
          )}
          <div>
            <CopyPreviewButton
              value={approval.diffPreview}
              label={t("permissions.approval.localAction.copyDiffPreview", {
                defaultValue: "Copy diff preview",
              })}
            />
          </div>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">
          {t("permissions.approval.localAction.diffPreviewUnavailable", {
            defaultValue: "Diff preview unavailable.",
          })}
        </span>
      )}
      <p className="text-xs">
        {t("permissions.approval.localAction.staleWriteWarning", {
          defaultValue: STALE_WRITE_WARNING,
        })}
      </p>
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
