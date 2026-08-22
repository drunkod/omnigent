// Shells tab content for the right-side rail: a virtual "+ New shell"
// row on top, then the session's shells as rows. Clicking a shell row
// does NOT open an in-rail split — it hands the shell to `onExpand`,
// which replaces the main session view with that shell
// (MainTerminalView for terminal-first sessions, the full-width push
// panel otherwise). The rail stays a lightweight index; the terminal
// always gets the full main column.

import { TerminalIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { inventoryTerminals, terminalTabKey, useTerminals } from "@/hooks/useTerminals";
import { NewTerminalButton } from "./NewTerminalButton";
import { useTerminalFirst } from "./TerminalFirstContext";
import { TerminalStatusBadge } from "./terminalStatus";
import { useTerminalStatuses } from "./useTerminalStatuses";

interface InlineTerminalsSectionProps {
  conversationId: string;
  /** Open a shell in the main view, keyed by its terminal tab key. */
  onExpand: (terminalKey: string) => void;
}

export function InlineTerminalsSection({ conversationId, onExpand }: InlineTerminalsSectionProps) {
  const { t } = useTranslation();
  const { terminals: allTerminals, isLoading, error } = useTerminals(conversationId);
  // Inventory view: the agent's own terminal (SDK REPL / native vendor
  // pane) backs the pill's Terminal view and must not appear as a
  // shell row here.
  const terminalFirstCtx = useTerminalFirst();
  const terminals = useMemo(
    () => inventoryTerminals(allTerminals, terminalFirstCtx?.isTerminalFirst ?? false),
    [allTerminals, terminalFirstCtx?.isTerminalFirst],
  );
  const { getStatus } = useTerminalStatuses(terminals, conversationId);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-card">
      {/* Always a plain top-aligned list: a virtual "+ New shell" row
          first (gated inside NewTerminalButton on the agent's terminal
          access — leading keeps it at a fixed spot instead of drifting
          down as shells accumulate), then the shell rows. With zero
          shells the virtual row is the whole list — no centered
          empty-state copy. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto py-1">
        <NewTerminalButton conversationId={conversationId} onCreated={onExpand} variant="row" />
        {isLoading && terminals.length === 0 && (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">
            {t("panels.terminals.loading", { defaultValue: "Loading terminals…" })}
          </div>
        )}
        {!isLoading && error !== null && terminals.length === 0 && (
          <div className="px-2 py-1.5 text-xs text-destructive">
            {t("panels.terminals.error", {
              error: error.message,
              defaultValue: "Failed to load terminals: {{error}}",
            })}
          </div>
        )}
        {terminals.map((terminal) => {
          const terminalLabel = [terminal.session, terminal.name].filter(Boolean).join(" ");
          return (
            <button
              key={terminalTabKey(terminal)}
              type="button"
              aria-label={t("panels.terminals.expand", {
                terminal: terminalLabel,
                defaultValue: "Expand {{terminal}}",
              })}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-accent/60"
              onClick={() => onExpand(terminalTabKey(terminal))}
            >
              <TerminalIcon className="size-3.5 shrink-0 text-muted-foreground" />
              {terminal.session && (
                <span className="shrink-0 text-xs font-medium">{terminal.session}</span>
              )}
              <span className="truncate text-xs text-muted-foreground/70">{terminal.name}</span>
              <span className="flex-1" />
              <TerminalStatusBadge status={getStatus(terminal)} />
            </button>
          );
        })}
      </div>
    </div>
  );
}
