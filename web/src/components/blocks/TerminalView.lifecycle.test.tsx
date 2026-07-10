import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConnectionState } from "./TerminalSession";
import { useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";
import { TerminalView } from "./TerminalView";

const terminalSessionMock = vi.hoisted(() => ({
  instances: [] as Array<{
    url: string;
    onState: (state: ConnectionState) => void;
    dispose: ReturnType<typeof vi.fn>;
    setInputEnabled: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("./TerminalSession", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./TerminalSession")>()),
  TerminalSession: class {
    dispose = vi.fn();
    setTheme = vi.fn();
    setFont = vi.fn();
    setInputEnabled = vi.fn();

    constructor(
      _container: HTMLDivElement,
      url: string,
      onState: (state: ConnectionState) => void,
    ) {
      terminalSessionMock.instances.push({
        url,
        onState,
        dispose: this.dispose,
        setInputEnabled: this.setInputEnabled,
      });
    }
  },
}));

beforeEach(() => {
  terminalSessionMock.instances = [];
  useTerminalLifecycleStore.setState({ byConversation: {} });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderAndAttach(transport?: "control" | "pty") {
  render(
    <TerminalView
      sessionId="conv_abc"
      terminalId="terminal_bash_s1"
      transport={transport}
    />,
  );
  await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(1));
}

describe("TerminalView lifecycle recovery", () => {
  it("reattaches after a refresh that mounted while the runner was offline", async () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      runnerId: "runner_1",
      state: "runner_offline",
    });
    await renderAndAttach("control");

    act(() => {
      terminalSessionMock.instances[0].onState({ kind: "runner_offline" });
      useTerminalLifecycleStore.getState().applyRunnerState({
        type: "session_runner_state",
        conversationId: "conv_abc",
        runnerId: "runner_1",
        state: "runner_reconnected",
      });
      useTerminalLifecycleStore.getState().applyTerminalState({
        type: "session_terminal_state",
        conversationId: "conv_abc",
        terminalId: "terminal_bash_s1",
        state: "terminal_running",
      });
    });

    await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(2));
    expect(terminalSessionMock.instances[0].dispose).toHaveBeenCalledOnce();
  });

  it("offers a working Attach action and clears a stale detached overlay", async () => {
    await renderAndAttach("control");
    act(() => {
      useTerminalLifecycleStore.getState().applyTerminalState({
        type: "session_terminal_state",
        conversationId: "conv_abc",
        terminalId: "terminal_bash_s1",
        state: "terminal_detached",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Attach" }));

    await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(2));
    act(() => terminalSessionMock.instances[1].onState({ kind: "connected" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Attach" })).toBeNull());
    expect(terminalSessionMock.instances[1].setInputEnabled).toHaveBeenLastCalledWith(true);
  });

  it("offers a working Retry action and clears a stale failed overlay", async () => {
    await renderAndAttach("control");
    act(() => {
      useTerminalLifecycleStore.getState().applyTerminalState({
        type: "session_terminal_state",
        conversationId: "conv_abc",
        terminalId: "terminal_bash_s1",
        state: "terminal_failed",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(2));
    act(() => terminalSessionMock.instances[1].onState({ kind: "connected" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry" })).toBeNull());
    expect(terminalSessionMock.instances[1].setInputEnabled).toHaveBeenLastCalledWith(true);
  });

  it("renders one preserved-session message when both SSE and close code report offline", async () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      runnerId: "runner_1",
      state: "runner_offline",
    });
    await renderAndAttach("control");

    act(() => {
      terminalSessionMock.instances[0].onState({ kind: "runner_offline" });
    });

    expect(screen.getAllByTestId("terminal-runner-offline")).toHaveLength(1);
    expect(screen.queryByText(/^Runner offline$/)).toBeNull();
  });

  it("does not redial PTY when an unadvertised legacy PTY attach returns 4406", async () => {
    await renderAndAttach();
    expect(terminalSessionMock.instances[0].url).toContain("transport=pty");

    act(() => {
      terminalSessionMock.instances[0].onState({ kind: "retry_with_pty" });
    });

    await screen.findByText("Bridge closed: PTY transport unavailable");
    expect(terminalSessionMock.instances).toHaveLength(1);
  });
});
