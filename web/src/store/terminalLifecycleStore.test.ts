import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  RECONNECT_SETTLE_TIMEOUT_MS,
  selectRunnerState,
  selectTerminalState,
  useTerminalLifecycleStore,
} from "./terminalLifecycleStore";

describe("terminal lifecycle store", () => {
  beforeEach(() => useTerminalLifecycleStore.setState({ byConversation: {} }));

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("tracks runner offline state per conversation", () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "runner_offline",
    );
    expect(selectRunnerState("c2")(useTerminalLifecycleStore.getState())).toBe(
      "online",
    );
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

    expect(
      selectTerminalState("c1", "t1")(useTerminalLifecycleStore.getState()),
    ).toBe("terminal_unknown");
    store.applyTerminalState({
      type: "session_terminal_state",
      conversationId: "c1",
      terminalId: "t1",
      state: "terminal_relaunching",
    });
    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "online",
    );
  });

  it("ends reconciling on a confirmed attach without a terminal-state frame", () => {
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

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "online",
    );
  });

  it("settles reconnect when the runner returns with no attachable terminal", () => {
    vi.useFakeTimers();
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_reconnected",
    });

    vi.advanceTimersByTime(RECONNECT_SETTLE_TIMEOUT_MS);

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "online",
    );
  });

  it("does not let the watchdog overwrite a newer offline edge", () => {
    vi.useFakeTimers();
    const store = useTerminalLifecycleStore.getState();
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_reconnected",
    });
    store.applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });

    vi.advanceTimersByTime(RECONNECT_SETTLE_TIMEOUT_MS);

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "runner_offline",
    );
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

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "runner_offline",
    );
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

    expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe(
      "online",
    );
    expect(selectRunnerState("c2")(useTerminalLifecycleStore.getState())).toBe(
      "runner_offline",
    );
  });
});
