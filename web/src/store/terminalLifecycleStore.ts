import { create } from "zustand";
import type {
  SessionRunnerStateEvent,
  SessionTerminalStateEvent,
  TerminalUiState,
} from "@/lib/events";

export type RunnerUiState = "online" | "runner_offline" | "runner_reconnected";

export type TerminalPanelState = Exclude<TerminalUiState, "runner_offline" | "runner_reconnected">;

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
  clearConversation: (conversationId: string) => void;
}

const EMPTY: ConversationLifecycle = {
  runnerState: "online",
  lastRunnerId: null,
  lastStateAt: 0,
  terminalStateById: {},
};

export const useTerminalLifecycleStore = create<TerminalLifecycleStore>((set) => ({
  byConversation: {},

  applyRunnerState: (event) =>
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
              event.state === "runner_reconnected" ? {} : previous.terminalStateById,
          },
        },
      };
    }),

  applyTerminalState: (event) =>
    set((state) => {
      const previous = state.byConversation[event.conversationId] ?? EMPTY;
      return {
        byConversation: {
          ...state.byConversation,
          [event.conversationId]: {
            ...previous,
            runnerState:
              previous.runnerState === "runner_reconnected" ? "online" : previous.runnerState,
            lastStateAt: Date.now(),
            terminalStateById: {
              ...previous.terminalStateById,
              [event.terminalId]: event.state,
            },
          },
        },
      };
    }),

  clearConversation: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.byConversation)) return state;
      const next = { ...state.byConversation };
      delete next[conversationId];
      return { byConversation: next };
    }),
}));

export function selectRunnerState(conversationId: string) {
  return (state: TerminalLifecycleStore): RunnerUiState =>
    state.byConversation[conversationId]?.runnerState ?? "online";
}

export function selectTerminalState(conversationId: string, terminalId: string) {
  return (state: TerminalLifecycleStore): TerminalPanelState =>
    state.byConversation[conversationId]?.terminalStateById[terminalId] ?? "terminal_unknown";
}
