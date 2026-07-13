import { describe, expect, it } from "vitest";

import { runnerDisplayLabel } from "@/components/HostCapabilityPanel";
import type { LocalRunnerSummary } from "@/lib/remoteRunner";

function runner(workspaces: LocalRunnerSummary["workspaces"]): LocalRunnerSummary {
  return {
    runner_id: "runner_token_secret-looking-id",
    online: true,
    harnesses: [],
    terminal_transports: [],
    tool_capabilities: [],
    workspaces,
  };
}

describe("runnerDisplayLabel", () => {
  it("uses the workspace display name instead of the runner id", () => {
    expect(
      runnerDisplayLabel(
        runner([{ workspace_id: "ws_1", display_name: "omnigent", capabilities: [] }]),
      ),
    ).toBe("omnigent runner");
  });

  it("falls back without exposing the runner id", () => {
    expect(runnerDisplayLabel(runner([]))).toBe("Local runner");
  });
});
