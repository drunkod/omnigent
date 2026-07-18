import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useTerminalLifecycleStore } from "@/store/terminalLifecycleStore";
import { RunnerStatusBadge } from "./RunnerStatusBadge";

describe("RunnerStatusBadge", () => {
  beforeEach(() => useTerminalLifecycleStore.setState({ byConversation: {} }));

  it("does not render for managed sessions", () => {
    render(<RunnerStatusBadge conversationId="c1" executionMode="managed" />);
    expect(screen.queryByTestId("runner-status-badge")).not.toBeInTheDocument();
  });

  it("renders the local runner badge", () => {
    render(<RunnerStatusBadge conversationId="c1" executionMode="local_runner" />);
    expect(screen.getByTestId("runner-status-badge")).toHaveTextContent("Local runner");
  });

  it("shows the persisted workspace and policy", () => {
    render(
      <RunnerStatusBadge
        conversationId="c1"
        executionMode="local_runner"
        workspaceLabel="project"
        policyMode="assisted"
      />,
    );
    expect(screen.getByTestId("runner-status-badge")).toHaveTextContent("Local · project");
    expect(screen.getByTitle(/assisted permissions/)).toBeInTheDocument();
  });

  it("shows preserved-session copy when the lifecycle event reports offline", () => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "c1",
      runnerId: "r1",
      state: "runner_offline",
    });
    render(<RunnerStatusBadge conversationId="c1" executionMode="local_runner" />);
    expect(screen.getByTestId("runner-status-badge")).toHaveTextContent("Local runner offline");
    expect(screen.getByText(/session is preserved/i)).toBeInTheDocument();
  });
});
