import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ConnectionState } from "./TerminalSession";
import { TerminalView } from "./TerminalView";
import { useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";

const terminalSessionMock = vi.hoisted(() => ({
  instances: [] as Array<{
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
    setInputEnabled = vi.fn();

    constructor(
      _container: HTMLDivElement,
      _url: string,
      onState: (state: ConnectionState) => void,
    ) {
      terminalSessionMock.instances.push({
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

it("preserves runner-offline state across a panel remount and reattaches after recovery", async () => {
  const lifecycle = useTerminalLifecycleStore.getState();
  lifecycle.applyRunnerState({
    type: "session_runner_state",
    conversationId: "conv_refresh",
    runnerId: "runner_local",
    state: "runner_offline",
  });

  const firstMount = render(
    <TerminalView sessionId="conv_refresh" terminalId="terminal_probe" transport="control" />,
  );
  await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(1));
  act(() => terminalSessionMock.instances[0].onState({ kind: "runner_offline" }));
  expect(screen.getByTestId("terminal-runner-offline")).toHaveTextContent("Session is preserved");

  firstMount.unmount();
  expect(useTerminalLifecycleStore.getState().byConversation.conv_refresh?.runnerState).toBe(
    "runner_offline",
  );

  render(<TerminalView sessionId="conv_refresh" terminalId="terminal_probe" transport="control" />);
  await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(2));
  act(() => terminalSessionMock.instances[1].onState({ kind: "runner_offline" }));
  expect(screen.getByTestId("terminal-runner-offline")).toHaveTextContent("Session is preserved");

  act(() => {
    lifecycle.applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_refresh",
      runnerId: "runner_local",
      state: "runner_reconnected",
    });
    lifecycle.applyTerminalState({
      type: "session_terminal_state",
      conversationId: "conv_refresh",
      terminalId: "terminal_probe",
      state: "terminal_running",
    });
  });

  await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(3));
  expect(terminalSessionMock.instances[1].dispose).toHaveBeenCalledTimes(1);
});
