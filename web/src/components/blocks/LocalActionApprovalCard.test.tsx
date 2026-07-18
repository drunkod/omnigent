import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

afterEach(cleanup);

const base = {
  elicitationId: "elic_local",
  phase: "tool_call",
  policyName: "local_runner",
  requestedSchema: {},
  status: "pending" as const,
  response: null,
};

describe("local-action approval cards", () => {
  it("renders strict shell guarantees without raw producer content", () => {
    const secret = "Bearer secret-that-must-not-render";
    render(
      <ApprovalCard
        {...base}
        message={`raw ${secret}`}
        contentPreview={`raw preview ${secret}`}
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          workspaceLabel: "project",
          cwd: "src",
          pathSummary: [],
          commandPreview: "pytest [arguments hidden]",
          diffTruncated: false,
          riskFlags: ["shell"],
          shellGuarantee: "strict_workspace",
        }}
      />,
    );
    expect(screen.getByText(/Strict workspace sandbox/)).toBeDefined();
    expect(screen.queryByText(/Trusted-machine shell/)).toBeNull();
    expect(screen.getByLabelText("Command preview").textContent).toContain(
      "pytest [arguments hidden]",
    );
    expect(screen.queryByText(secret)).toBeNull();
  });

  it("renders trusted and unknown shell copy conservatively", () => {
    const { rerender } = render(
      <ApprovalCard
        {...base}
        message="shell"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          pathSummary: [],
          diffTruncated: false,
          riskFlags: [],
          shellGuarantee: "trusted_machine",
        }}
      />,
    );
    expect(screen.getByText(/Trusted-machine shell/)).toBeDefined();
    rerender(
      <ApprovalCard
        {...base}
        message="shell"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "run_shell",
          policyMode: "manual",
          pathSummary: [],
          diffTruncated: false,
          riskFlags: [],
        }}
      />,
    );
    expect(screen.getByText(/Shell isolation was not reported/)).toBeDefined();
    expect(screen.getByText(/Command preview unavailable/)).toBeDefined();
  });

  it("renders write diff, truncation, paths, and stale-review warning", () => {
    render(
      <ApprovalCard
        {...base}
        message="write"
        contentPreview=""
        localAction={{
          version: 1,
          kind: "write_file",
          policyMode: "assisted",
          pathSummary: ["src/app.ts"],
          diffPreview: "--- a/src/app.ts\n+++ b/src/app.ts",
          diffTruncated: true,
          riskFlags: ["writes_files"],
        }}
      />,
    );
    expect(screen.getByText("src/app.ts")).toBeDefined();
    expect(screen.getByLabelText("Diff preview")).toBeDefined();
    expect(screen.getByText(/Diff preview was truncated/)).toBeDefined();
    expect(screen.getByText(/checked again immediately before execution/)).toBeDefined();
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDefined();
  });
});
