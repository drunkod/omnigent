import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";

vi.mock("@/hooks/RunnerHealthProvider", () => ({
  useSessionRunnerOnline: vi.fn(),
}));

import { useSessionRunnerOnline } from "@/hooks/RunnerHealthProvider";
import { useTerminalRunnerLifecycle } from "./useTerminalRunnerLifecycle";

const useSessionRunnerOnlineMock = vi.mocked(useSessionRunnerOnline);

beforeEach(() => {
  useSessionRunnerOnlineMock.mockReturnValue(undefined);
  useTerminalLifecycleStore.setState({ byConversation: {} });
});

afterEach(() => {
  useTerminalLifecycleStore.getState().clearConversation("conv_abc");
  cleanup();
  vi.clearAllMocks();
});

describe("useTerminalRunnerLifecycle", () => {
  it("turns a poll-only outage into terminal offline and reconnect lifecycle", async () => {
    useSessionRunnerOnlineMock.mockReturnValue(false);
    const { result, rerender } = renderHook(() =>
      useTerminalRunnerLifecycle("conv_abc"),
    );

    expect(result.current).toBe("runner_offline");
    await waitFor(() =>
      expect(
        useTerminalLifecycleStore.getState().byConversation.conv_abc?.runnerState,
      ).toBe("runner_offline"),
    );

    useSessionRunnerOnlineMock.mockReturnValue(true);
    rerender();

    await waitFor(() =>
      expect(
        useTerminalLifecycleStore.getState().byConversation.conv_abc?.runnerState,
      ).toBe("runner_reconnected"),
    );
  });

  it("does not override SSE lifecycle before the health poll resolves", () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      runnerId: "runner_1",
      state: "runner_offline",
    });

    const { result } = renderHook(() =>
      useTerminalRunnerLifecycle("conv_abc"),
    );

    expect(result.current).toBe("runner_offline");
    expect(
      useTerminalLifecycleStore.getState().byConversation.conv_abc?.lastRunnerId,
    ).toBe("runner_1");
  });
});
