import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { usePersistentActiveKey } from "./usePersistentActiveKey";

describe("usePersistentActiveKey", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("restores the selected terminal for the same conversation", () => {
    const first = renderHook(() => usePersistentActiveKey("conv_1"));
    act(() => first.result.current[1]("terminal:terminal_shell_1"));
    first.unmount();

    const restored = renderHook(() => usePersistentActiveKey("conv_1"));
    expect(restored.result.current[0]).toBe("terminal:terminal_shell_1");
  });

  it("does not leak a selection into another conversation", () => {
    window.sessionStorage.setItem(
      "omnigent.activeTerminalKey.conv_1",
      "terminal:terminal_shell_1",
    );
    const other = renderHook(() => usePersistentActiveKey("conv_2"));
    expect(other.result.current[0]).toBeNull();
  });

  it("clears the persisted key when the selection becomes stale", () => {
    const hook = renderHook(() => usePersistentActiveKey("conv_1"));
    act(() => hook.result.current[1]("terminal:terminal_shell_1"));
    act(() => hook.result.current[1](null));

    expect(
      window.sessionStorage.getItem("omnigent.activeTerminalKey.conv_1"),
    ).toBeNull();
    expect(hook.result.current[0]).toBeNull();
  });
});
