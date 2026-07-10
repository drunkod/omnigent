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
