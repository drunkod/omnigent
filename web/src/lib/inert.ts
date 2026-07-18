/** Serialize inert for React 18, which warns when a false value reaches the DOM. */
export function inertProps(enabled: boolean): { inert?: boolean } {
  return (enabled ? { inert: "" } : {}) as unknown as { inert?: boolean };
}
