import { useEffect, useState } from "react";
import { type TerminalInfo, terminalTabKey } from "@/hooks/useTerminals";
import { selectTerminalState, useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";

/** Keep a deleted terminal mounted only long enough to show its exited state. */
export function useRetainedActiveTerminal(
  conversationId: string,
  terminals: TerminalInfo[],
  activeKey: string | null,
) {
  const liveTerminal =
    activeKey !== null ? (terminals.find((t) => terminalTabKey(t) === activeKey) ?? null) : null;
  const [lastActiveTerminal, setLastActiveTerminal] = useState<TerminalInfo | null>(null);

  useEffect(() => {
    if (liveTerminal) setLastActiveTerminal(liveTerminal);
  }, [liveTerminal]);

  const retainedMatches =
    activeKey !== null &&
    lastActiveTerminal !== null &&
    terminalTabKey(lastActiveTerminal) === activeKey;
  const retainedState = useTerminalLifecycleStore(
    selectTerminalState(conversationId, retainedMatches ? lastActiveTerminal.id : ""),
  );
  const exitedTerminal =
    liveTerminal === null && retainedMatches && retainedState === "terminal_exited"
      ? lastActiveTerminal
      : null;

  return {
    activeTerminal: liveTerminal ?? exitedTerminal,
    isExitedTombstone: exitedTerminal !== null,
  };
}
