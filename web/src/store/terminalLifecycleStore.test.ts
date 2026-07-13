import { beforeEach, describe, expect, it } from "vitest";
import {
  selectRunnerState,
  selectTerminalState,
  useTerminalLifecycleStore,
} from "./terminalLifecycleStore";

describe("terminal lifecycle store", () => {
  beforeEach(() => useTerminalLifecycleStore.setState({ byConversation: {} }));

  it("tracks runner offline state per conversation", () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("runner_offline");
    expect(selectRunnerState("c2")(useTerminalLifecycleStore.getState())).toBe("online");
  });

  it("clears stale terminals on reconnect and ends reconciling on the first terminal frame", () => {
    const store = useTerminalLifecycleStore.getState();
    store.applyTerminalState({
      type: "session_terminal_state",
      conversationId: "c1",
      terminalId: "t1",
      state: "terminal_running",
    });
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_reconnected",
    });

    expect(selectTerminalState("c1", "t1")(useTerminalLifecycleStore.getState())).toBe(
      "terminal_unknown",
    );
    store.applyTerminalState({
      type: "session_terminal_state",
      conversationId: "c1",
      terminalId: "t1",
      state: "terminal_relaunching",
    });
    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("online");
  });

  it("ends reconciling on a confirmed attach without a terminal-state frame", () => {
    // Reproduces the live deadlock: after a runner reconnect the bridge
    // reaches "connected" but the runner re-attaches an already-running
    // terminal without re-emitting a terminal-state event. A confirmed attach
    // must return the conversation to "online" on its own.
    const store = useTerminalLifecycleStore.getState();
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_reconnected",
    });
    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "runner_reconnected",
    );

    store.confirmRunnerAttached("c1");

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("online");
  });

  it("never overrides an authoritative runner_offline on a confirmed attach", () => {
    const store = useTerminalLifecycleStore.getState();
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });

    store.confirmRunnerAttached("c1");

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("runner_offline");
  });

  it("is a no-op for an unknown conversation on a confirmed attach", () => {
    const store = useTerminalLifecycleStore.getState();
    store.confirmRunnerAttached("unknown");

    expect(useTerminalLifecycleStore.getState().byConversation).toEqual({});
  });

  it("clears a conversation without affecting another conversation", () => {
    const store = useTerminalLifecycleStore.getState();
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c2",
      runnerId: "r2",
      state: "runner_offline",
    });
    store.clearConversation("c1");

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("online");
    expect(selectRunnerState("c2")(useTerminalLifecycleStore.getState())).toBe("runner_offline");
  });
});
