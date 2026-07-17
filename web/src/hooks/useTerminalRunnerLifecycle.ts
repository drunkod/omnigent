import { useEffect } from "react";
import { useSessionRunnerOnline } from "@/hooks/RunnerHealthProvider";
import {
  type RunnerUiState,
  useTerminalLifecycleStore,
} from "@/store/terminalLifecycleStore";

const HEALTH_POLL_RUNNER_ID = "runner_health_poll";

/**
 * Reconcile the open session's tunnel-accurate health poll with terminal UI
 * lifecycle state.
 *
 * Runner lifecycle SSE is still the preferred low-latency source, but a killed
 * runner can leave that edge unseen while the host remains online. The shared
 * `/health` poll is authoritative for strict tunnel reachability, so a known
 * offline value must drive the existing TerminalView offline overlay and input
 * gate. When the poll recovers before an SSE reconnect edge arrives, synthesize
 * the normal `runner_reconnected` transition; the fresh terminal attach (or the
 * store watchdog) settles it back to online.
 *
 * `undefined` means the poll has not resolved and never overrides SSE state.
 */
export function useTerminalRunnerLifecycle(
  conversationId: string | undefined,
): RunnerUiState {
  const polledOnline = useSessionRunnerOnline(conversationId);
  const lifecycle = useTerminalLifecycleStore((state) =>
    conversationId ? state.byConversation[conversationId] : undefined,
  );
  const runnerState = lifecycle?.runnerState ?? "online";
  const runnerId = lifecycle?.lastRunnerId ?? HEALTH_POLL_RUNNER_ID;

  useEffect(() => {
    if (!conversationId || polledOnline === undefined) return;

    const store = useTerminalLifecycleStore.getState();
    const current = store.byConversation[conversationId];
    const currentState = current?.runnerState ?? "online";
    const currentRunnerId = current?.lastRunnerId ?? runnerId;

    if (polledOnline === false && currentState !== "runner_offline") {
      store.applyRunnerState({
        type: "session_runner_state",
        conversationId,
        runnerId: currentRunnerId,
        state: "runner_offline",
      });
      return;
    }

    if (polledOnline === true && currentState === "runner_offline") {
      store.applyRunnerState({
        type: "session_runner_state",
        conversationId,
        runnerId: currentRunnerId,
        state: "runner_reconnected",
      });
    }
  }, [conversationId, polledOnline, runnerId]);

  // Reflect a known poll outage immediately; the effect above then writes the
  // same state into the shared store for TerminalView and status consumers.
  return polledOnline === false ? "runner_offline" : runnerState;
}
