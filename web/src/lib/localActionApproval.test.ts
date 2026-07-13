import { describe, expect, it } from "vitest";
import { parseLocalActionApproval } from "./localActionApproval";

describe("parseLocalActionApproval", () => {
  it("normalizes a valid write payload", () => {
    expect(
      parseLocalActionApproval({
        version: 1,
        action_id: "act_1",
        kind: "write_file",
        policy_mode: "manual",
        workspace_label: "project",
        path_summary: ["src/app.ts"],
        diff_preview: "--- a/src/app.ts\n+++ b/src/app.ts",
        diff_truncated: false,
        risk_flags: ["writes_files"],
      }),
    ).toEqual({
      version: 1,
      actionId: "act_1",
      kind: "write_file",
      policyMode: "manual",
      workspaceLabel: "project",
      pathSummary: ["src/app.ts"],
      diffPreview: "--- a/src/app.ts\n+++ b/src/app.ts",
      diffTruncated: false,
      riskFlags: ["writes_files"],
    });
  });

  it("carries an explicit shell guarantee", () => {
    const parsed = parseLocalActionApproval({
      version: 1,
      kind: "run_shell",
      policy_mode: "assisted",
      path_summary: [],
      command_preview: "pytest [arguments hidden]",
      diff_truncated: false,
      risk_flags: ["shell"],
      shell_guarantee: "strict_workspace",
    });
    expect(parsed?.shellGuarantee).toBe("strict_workspace");
  });

  it("rejects apply_patch and invalid policy modes", () => {
    expect(
      parseLocalActionApproval({ version: 1, kind: "apply_patch", policy_mode: "manual" }),
    ).toBeNull();
    expect(
      parseLocalActionApproval({ version: 1, kind: "write_file", policy_mode: "unsafe" }),
    ).toBeNull();
  });

  it("drops malformed optional fields without recovering raw content", () => {
    const parsed = parseLocalActionApproval({
      version: 1,
      kind: "run_shell",
      policy_mode: "manual",
      cwd: "/absolute/private/path",
      command_preview: "x".repeat(2_001),
      path_summary: ["ok", 42],
      diff_truncated: false,
      risk_flags: ["shell"],
    });
    expect(parsed).not.toBeNull();
    expect(parsed?.cwd).toBeUndefined();
    expect(parsed?.commandPreview).toBeUndefined();
    expect(parsed?.pathSummary).toEqual([]);
  });
});
