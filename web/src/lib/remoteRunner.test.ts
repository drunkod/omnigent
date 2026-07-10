import { describe, expect, it } from "vitest";
import { attachQuery, stateFromAttachClose } from "./remoteRunner";

describe("remote runner attach contract", () => {
  it("prefers control when advertised", () => {
    expect(attachQuery({ transports: ["control", "pty"], readOnly: false })).toBe(
      "transport=control",
    );
  });

  it("falls back to pty when control is absent", () => {
    expect(attachQuery({ transports: ["pty"], readOnly: true })).toBe(
      "transport=pty&read_only=true",
    );
  });

  it("lets the debug override win", () => {
    expect(attachQuery({ transports: ["control"], debugOverride: "pty", readOnly: false })).toBe(
      "transport=pty",
    );
  });

  it("maps lifecycle close codes and leaves generic codes alone", () => {
    expect(stateFromAttachClose(4503)).toBe("runner_offline");
    expect(stateFromAttachClose(4404)).toBe("terminal_exited");
    expect(stateFromAttachClose(4405)).toBe("terminal_detached");
    expect(stateFromAttachClose(1006)).toBeNull();
    expect(stateFromAttachClose(1011)).toBeNull();
  });
});
