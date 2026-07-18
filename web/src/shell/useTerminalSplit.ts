// Shared data hook for InlineTerminalsSection and TerminalsPanel.

import { useEffect, useMemo } from "react";
import { useResizableColumn } from "@/hooks/useResizableColumn";
import { inventoryTerminals, terminalTabKey, useTerminals } from "@/hooks/useTerminals";
import { selectRunnerState, useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";
import { useTerminalFirst } from "./TerminalFirstContext";
import { usePersistentActiveKey } from "./usePersistentActiveKey";
import { useRetainedActiveTerminal } from "./useRetainedActiveTerminal";
import { useTerminalStatuses } from "./useTerminalStatuses";

// Only the terminal the user actually selects opens a WebSocket (via
// ``TerminalView``). Opening the panel used to fan out a read-only
// ``tmux attach`` to every unselected terminal for status badges; with N
// terminals that meant N simultaneous ``pty.fork`` + ``tmux attach`` on
// the runner, which could take the runner down. Unselected terminals now
// derive their badge from the resource ``running`` flag alone (see
// ``deriveTerminalStatus``).
export function useTerminalSplit(conversationId: string) {
  const { terminals: allTerminals, isLoading } = useTerminals(conversationId);
  // Inventory view: the agent's own terminal (SDK REPL / native vendor
  // pane) backs the pill's Terminal view and must not appear as a
  // shell row here.
  const terminalFirstCtx = useTerminalFirst();
  const terminals = useMemo(
    () => inventoryTerminals(allTerminals, terminalFirstCtx?.isTerminalFirst ?? false),
    [allTerminals, terminalFirstCtx?.isTerminalFirst],
  );
  const [activeKey, setActiveKey] = usePersistentActiveKey(conversationId, "rail");
  const runnerState = useTerminalLifecycleStore(selectRunnerState(conversationId));
  const { getStatus, setTerminalConnectionState, markTerminalActive } = useTerminalStatuses(
    terminals,
    conversationId,
  );

  const { activeTerminal, isExitedTombstone } = useRetainedActiveTerminal(
    conversationId,
    terminals,
    activeKey,
  );

  const {
    width: listWidth,
    containerRef: splitRef,
    handleProps: columnHandleProps,
  } = useResizableColumn();

  // Clear a genuinely stale selection only after the authoritative inventory
  // has loaded while the runner is online. During offline/reconnect windows an
  // empty list is transient and must not erase the key needed after reload.
  useEffect(() => {
    if (activeKey === null || isLoading || runnerState !== "online") return;
    if (!terminals.some((t) => terminalTabKey(t) === activeKey) && !isExitedTombstone) {
      setActiveKey(null);
    }
  }, [terminals, activeKey, isExitedTombstone, isLoading, runnerState, setActiveKey]);

  return {
    terminals,
    activeKey,
    setActiveKey,
    activeTerminal,
    getStatus,
    setTerminalConnectionState,
    markTerminalActive,
    listWidth,
    splitRef,
    columnHandleProps,
  };
}
