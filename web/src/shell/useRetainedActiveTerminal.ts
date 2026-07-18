import { useEffect, useState } from "react";
import { type TerminalInfo, terminalTabKey } from "@/hooks/useTerminals";
import {
  selectRunnerState,
  selectTerminalState,
  useTerminalLifecycleStore,
} from "@/store/terminalLifecycleStore";

/**
 * Keep a selected terminal mounted long enough to render its exited state.
 *
 * The resource-deleted SSE edge can beat both the attach WebSocket's 4404 close
 * and the runner's terminal-state reconciliation. When the runner is still
 * online, disappearance of the selected last-known resource means that terminal
 * ended, not that the whole runner vanished. Retain it immediately and publish
 * the missing `terminal_exited` state so the overlay and Close shell affordance
 * remain available. Runner outages do not use this inference; their cached
 * inventory and runner-offline lifecycle remain authoritative.
 */
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
  const runnerState = useTerminalLifecycleStore(selectRunnerState(conversationId));
  const retainedState = useTerminalLifecycleStore(
    selectTerminalState(conversationId, retainedMatches ? lastActiveTerminal.id : ""),
  );
  const inferredExited = liveTerminal === null && retainedMatches && runnerState === "online";

  useEffect(() => {
    if (!inferredExited || lastActiveTerminal === null || retainedState === "terminal_exited") {
      return;
    }
    useTerminalLifecycleStore.getState().applyTerminalState({
      type: "session_terminal_state",
      conversationId,
      terminalId: lastActiveTerminal.id,
      state: "terminal_exited",
    });
  }, [conversationId, inferredExited, lastActiveTerminal, retainedState]);

  const exitedTerminal =
    liveTerminal === null &&
    retainedMatches &&
    (retainedState === "terminal_exited" || inferredExited)
      ? lastActiveTerminal
      : null;

  return {
    activeTerminal: liveTerminal ?? exitedTerminal,
    isExitedTombstone: exitedTerminal !== null,
  };
}
