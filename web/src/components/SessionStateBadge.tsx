// Sidebar status indicator. Approval surfaces as a "Needs response" tag so
// it reads at a glance; running/unseen stay as compact dots. Verbose copy
// (incl. the approval count) lives in the tooltip.

import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { RunningDot } from "@/components/RunningDot";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { SessionState } from "@/hooks/useSessionState";
import { cn } from "@/lib/utils";
import type { ReactElement } from "react";

export interface SessionStateBadgeProps {
  state: SessionState;
}

interface Visual {
  kind: SessionState["kind"];
  ariaLabel: string;
  tooltip: string;
  render: () => ReactElement;
}

function describe(state: SessionState, t: TFunction): Visual {
  switch (state.kind) {
    case "awaiting": {
      const tooltip = t("misc.sessionState.approvalPromptWaiting", { count: state.count });
      return {
        kind: state.kind,
        ariaLabel: tooltip,
        tooltip,
        render: () => (
          <Badge className="border-transparent bg-warning/25 text-warning">
            {t("misc.sessionState.needsResponse")}
          </Badge>
        ),
      };
    }
    case "running":
      return {
        kind: state.kind,
        ariaLabel: t("misc.sessionState.running"),
        tooltip: t("misc.sessionState.running"),
        render: () => <RunningDot />,
      };
    case "unseen":
      // Solid brand-pink dot — distinguished from the running indicator,
      // which is a grey spinner.
      return {
        kind: state.kind,
        ariaLabel: t("misc.sessionState.newMessages"),
        tooltip: t("misc.sessionState.newMessages"),
        render: () => <Dot tone="bg-brand-accent" />,
      };
  }
}

function Dot({ tone }: { tone: string }) {
  return <span aria-hidden className={cn("size-2 shrink-0 rounded-full", tone)} />;
}

export function SessionStateBadge({ state }: SessionStateBadgeProps) {
  const { t } = useTranslation();
  const visual = describe(state, t);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          data-testid="session-state-badge"
          data-state={visual.kind}
          role="img"
          aria-label={visual.ariaLabel}
          className="inline-flex h-5 shrink-0 items-center justify-center"
        >
          {visual.render()}
        </span>
      </TooltipTrigger>
      {/* Opens left: the badge sits at the right edge of the narrow
          sidebar, so a right-opening tooltip would overflow the panel. */}
      <TooltipContent side="left">{visual.tooltip}</TooltipContent>
    </Tooltip>
  );
}
