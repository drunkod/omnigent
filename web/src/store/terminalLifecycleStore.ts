import { create } from "zustand";
import type {
  SessionRunnerStateEvent,
  SessionTerminalStateEvent,
  TerminalUiState,
} from "@/lib/events";

export type RunnerUiState = "online" | "runner_offline" | "runner_reconnected";

export type TerminalPanelState = Exclude<
  TerminalUiState,
  "runner_offline" | "runner_reconnected"
>;

interface ConversationLifecycle {
  runnerState: RunnerUiState;
  lastRunnerId: string | null;
  lastStateAt: number;
  terminalStateById: Record<string, TerminalPanelState>;
}

interface TerminalLifecycleStore {
  byConversation: Record<string, ConversationLifecycle>;
  applyRunnerState: (event: SessionRunnerStateEvent) => void;
  applyTerminalState: (event: SessionTerminalStateEvent) => void;
  confirmRunnerAttached: (conversationId: string) => void;
  settleReconciliation: (conversationId: string) => void;
  clearConversation: (conversationId: string) => void;
}

// The server bounds reconnect handling at 25 seconds. Give its settling
// terminal-state edge five seconds of delivery headroom, then release the UI
// even when that edge was lost or the restarted runner had no terminals.
export const RECONNECT_SETTLE_TIMEOUT_MS = 30_000;

const EMPTY: ConversationLifecycle = {
  runnerState: "online",
  lastRunnerId: null,
  lastStateAt: 0,
  terminalStateById: {},
};

const reconnectWatchdogs = new Map<string, ReturnType<typeof setTimeout>>();

function clearReconnectWatchdog(conversationId: string): void {
  const timer = reconnectWatchdogs.get(conversationId);
  if (timer === undefined) return;
  globalThis.clearTimeout(timer);
  reconnectWatchdogs.delete(conversationId);
}

export const useTerminalLifecycleStore = create<TerminalLifecycleStore>(
  (set, get) => ({
    byConversation: {},

    applyRunnerState: (event) => {
      set((state) => {
        const previous = state.byConversation[event.conversationId] ?? EMPTY;
        return {
          byConversation: {
            ...state.byConversation,
            [event.conversationId]: {
              ...previous,
              runnerState: event.state,
              lastRunnerId: event.runnerId,
              lastStateAt: Date.now(),
              terminalStateById:
                event.state === "runner_reconnected"
                  ? {}
                  : previous.terminalStateById,
            },
          },
        };
      });

      clearReconnectWatchdog(event.conversationId);
      if (event.state === "runner_reconnected") {
        const timer = globalThis.setTimeout(() => {
          reconnectWatchdogs.delete(event.conversationId);
          get().settleReconciliation(event.conversationId);
        }, RECONNECT_SETTLE_TIMEOUT_MS);
        reconnectWatchdogs.set(event.conversationId, timer);
      }
    },

    applyTerminalState: (event) => {
      set((state) => {
        const previous = state.byConversation[event.conversationId] ?? EMPTY;
        return {
          byConversation: {
            ...state.byConversation,
            [event.conversationId]: {
              ...previous,
              runnerState:
                previous.runnerState === "runner_reconnected"
                  ? "online"
                  : previous.runnerState,
              lastStateAt: Date.now(),
              terminalStateById: {
                ...previous.terminalStateById,
                [event.terminalId]: event.state,
              },
            },
          },
        };
      });
      clearReconnectWatchdog(event.conversationId);
    },

    // A live terminal attach proves a reconnect completed even when the runner
    // does not re-emit a terminal-state event.
    confirmRunnerAttached: (conversationId) => {
      set((state) => {
        const previous = state.byConversation[conversationId];
        if (!previous || previous.runnerState !== "runner_reconnected")
          return state;
        return {
          byConversation: {
            ...state.byConversation,
            [conversationId]: {
              ...previous,
              runnerState: "online",
              lastStateAt: Date.now(),
            },
          },
        };
      });
      clearReconnectWatchdog(conversationId);
    },

    // Defense in depth for an empty restarted runner, a failed reconcile POST,
    // or an SSE client that missed the terminal-state burst. The runner tunnel
    // is reachable again, so returning to online restores input and New shell;
    // individual dead terminals still retain their own closed/exited state.
    settleReconciliation: (conversationId) => {
      set((state) => {
        const previous = state.byConversation[conversationId];
        if (!previous || previous.runnerState !== "runner_reconnected")
          return state;
        return {
          byConversation: {
            ...state.byConversation,
            [conversationId]: {
              ...previous,
              runnerState: "online",
              lastStateAt: Date.now(),
            },
          },
        };
      });
      clearReconnectWatchdog(conversationId);
    },

    clearConversation: (conversationId) => {
      set((state) => {
        if (!(conversationId in state.byConversation)) return state;
        const next = { ...state.byConversation };
        delete next[conversationId];
        return { byConversation: next };
      });
      clearReconnectWatchdog(conversationId);
    },
  }),
);

export function selectRunnerState(conversationId: string) {
  return (state: TerminalLifecycleStore): RunnerUiState =>
    state.byConversation[conversationId]?.runnerState ?? "online";
}

export function selectTerminalState(
  conversationId: string,
  terminalId: string,
) {
  return (state: TerminalLifecycleStore): TerminalPanelState =>
    state.byConversation[conversationId]?.terminalStateById[terminalId] ??
    "terminal_unknown";
}
