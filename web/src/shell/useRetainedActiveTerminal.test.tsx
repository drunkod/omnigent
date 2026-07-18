import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { TerminalInfo } from "@/hooks/useTerminals";
import { useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";
import { useRetainedActiveTerminal } from "./useRetainedActiveTerminal";

const SHELL: TerminalInfo = {
  id: "terminal_bash_s1",
  name: "bash",
  session: "s1",
  running: true,
};

beforeEach(() => {
  useTerminalLifecycleStore.setState({ byConversation: {} });
});

afterEach(() => {
  useTerminalLifecycleStore.getState().clearConversation("conv_abc");
  cleanup();
});

describe("useRetainedActiveTerminal", () => {
  it("retains and marks an exited shell when deletion beats terminal_state", async () => {
    const { result, rerender } = renderHook(
      ({ terminals }) =>
        useRetainedActiveTerminal("conv_abc", terminals, "terminal:terminal_bash_s1"),
      { initialProps: { terminals: [SHELL] as TerminalInfo[] } },
    );

    expect(result.current.activeTerminal?.id).toBe(SHELL.id);
    rerender({ terminals: [] });

    expect(result.current.activeTerminal?.id).toBe(SHELL.id);
    expect(result.current.isExitedTombstone).toBe(true);
    await waitFor(() =>
      expect(
        useTerminalLifecycleStore.getState().byConversation.conv_abc?.terminalStateById[SHELL.id],
      ).toBe("terminal_exited"),
    );
  });

  it("does not infer terminal exit from a missing inventory while runner is offline", () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      runnerId: "runner_1",
      state: "runner_offline",
    });

    const { result, rerender } = renderHook(
      ({ terminals }) =>
        useRetainedActiveTerminal("conv_abc", terminals, "terminal:terminal_bash_s1"),
      { initialProps: { terminals: [SHELL] as TerminalInfo[] } },
    );

    rerender({ terminals: [] });

    expect(result.current.activeTerminal).toBeNull();
    expect(result.current.isExitedTombstone).toBe(false);
    expect(
      useTerminalLifecycleStore.getState().byConversation.conv_abc?.terminalStateById[SHELL.id],
    ).toBeUndefined();
  });
});
