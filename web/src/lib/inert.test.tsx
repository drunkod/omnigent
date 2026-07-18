import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { inertProps } from "@/lib/inert";

describe("inertProps", () => {
  it("serializes enabled inert and omits disabled inert", () => {
    expect(inertProps(true)).toEqual({ inert: "" });
    expect(inertProps(false)).toEqual({});
  });

  it("serializes through React DOM without warnings", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { getByTestId, rerender } = render(<div data-testid="target" {...inertProps(true)} />);

    expect(getByTestId("target")).toHaveAttribute("inert", "");

    rerender(<div data-testid="target" {...inertProps(false)} />);

    expect(getByTestId("target")).not.toHaveAttribute("inert");
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
