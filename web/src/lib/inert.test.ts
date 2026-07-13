import { describe, expect, it } from "vitest";

import { inertProps } from "@/lib/inert";

describe("inertProps", () => {
  it("serializes enabled inert and omits disabled inert", () => {
    expect(inertProps(true)).toEqual({ inert: "" });
    expect(inertProps(false)).toEqual({});
  });
});
