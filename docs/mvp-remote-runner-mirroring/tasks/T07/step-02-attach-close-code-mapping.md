# Step 02 — Attach close-code mapping + transport selection

**Commit 2 of T07.** Make the browser interpret T06's attach close-code
contract directly, and honor the terminal's advertised transport.

## Current state

`web/src/components/blocks/TerminalSession.ts` already:

- speaks `transport=control|pty` on the resource attach WS;
- classifies closes via `isUnexpectedTerminalClose(code)` — 1001/1006/1012/1013
  are transport-shaped and auto-reconnect; 1000/1008/4xxx are deliberate;
- surfaces state through `ConnectionState`:

```typescript
type ConnectionState =
  | { kind: "connecting" }
  | { kind: "connected" }
  | { kind: "closed"; reason: string; code: number }
  | { kind: "error" };
```

What's missing: 4xxx codes all collapse into a generic `closed` overlay. T06
standardized them; the UI must distinguish them.

## Task

### 1. Shared mapping: `web/src/lib/remoteRunner.ts` (new)

```typescript
import type { TerminalUiState } from "@/lib/events";

/** T06 attach close-code contract. */
export const ATTACH_CLOSE = {
  RUNNER_OFFLINE: 4503,
  TERMINAL_NOT_FOUND: 4404,
  TERMINAL_DETACHED: 4405,
  TRANSPORT_UNSUPPORTED: 4406,
} as const;

/**
 * Map an attach close code to a lifecycle UI state.
 * Returns null for codes the existing retry logic should keep handling
 * (transport-shaped drops) and for generic failures.
 */
export function stateFromAttachClose(code: number): TerminalUiState | null {
  switch (code) {
    case ATTACH_CLOSE.RUNNER_OFFLINE:     return "runner_offline";
    case ATTACH_CLOSE.TERMINAL_NOT_FOUND: return "terminal_exited";   // or terminal_unknown
    case ATTACH_CLOSE.TERMINAL_DETACHED:  return "terminal_detached"; // tmux alive, not a failure
    default:                              return null;
  }
}

/**
 * Build the attach query string from the terminal's advertised transports.
 * Missing advertisement means a legacy PTY terminal, not control support.
 */
export function attachQuery(opts: {
  transports: string[];                 // terminal-advertised transports
  debugOverride?: "control" | "pty";    // dev-settings escape hatch
  readOnly: boolean;
}): string {
  const transport =
    opts.debugOverride ?? (opts.transports.includes("control") ? "control" : "pty");
  const params = new URLSearchParams({ transport });
  if (opts.readOnly) params.set("read_only", "true");
  return params.toString();
}
```

Attach URL stays the **only** web terminal attach path:

```text
Advertised control: /v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach?transport=control
Legacy/missing:     /v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach?transport=pty
Debug:     ...?transport=pty
Observer:  ...&read_only=true
```

When `metadata.terminal_transport` advertises `control`, the browser owns
grid, scrollback, selection/copy, and byte-level pane output. Missing or
`pty` metadata preserves the legacy PTY behavior; `4406` remains the runtime
fallback from control to PTY.

### 2. Wire into the existing close handler

In `TerminalSession.ts`, consult the mapping **before** the transport-shaped
retry check. Do not replace the existing logic — extend it:

```typescript
this.ws.addEventListener("close", (ev) => {
  const mapped = stateFromAttachClose(ev.code);

  if (mapped === "runner_offline") {
    // No redial loop: wait for session.runner_state=runner_reconnected
    // (step-03) or an explicit user action.
    onState({ kind: "runner_offline" });
    return;
  }
  if (ev.code === ATTACH_CLOSE.TRANSPORT_UNSUPPORTED) {
    // control rejected -> one automatic retry on pty, then give up.
    // UX is "retry using PTY", never "terminal broken".
    onState({ kind: "retry_with_pty" });
    return;
  }
  if (mapped) {
    onState({ kind: "lifecycle", state: mapped });   // exited / detached
    return;
  }
  // ...existing path unchanged: isUnexpectedTerminalClose(ev.code)
  //    -> auto-reconnect; else generic closed overlay...
  onState({ kind: "closed", reason: ev.reason || `code ${ev.code}`, code: ev.code });
}, { signal: this.abort.signal });
```

Extend `ConnectionState` with the new variants (`runner_offline`,
`retry_with_pty`, `lifecycle`) rather than overloading `closed`, so
`useTerminalStatuses` and the panel can branch without re-parsing codes.

### 3. Full mapping reference

| Close code | Meaning (T06) | UI state | Reconnect behavior |
| --- | --- | --- | --- |
| `4503` | runner offline | `runner_offline` | no tight loop; wait for `runner_reconnected` event or user action |
| `4404` | terminal not found | `terminal_exited` / `terminal_unknown` | stop; show exited UI |
| `4405` | terminal detached | `terminal_detached` | show attach button — recoverable, not a failure |
| `4406` | transport unsupported | — | auto-retry once with `transport=pty` |
| `1001/1006/1012/1013` | transport drop | (existing) | existing auto-reconnect |
| `1011` / other | generic failure | (existing) | generic closed overlay |

## Acceptance

```text
4503 shows runner offline
4404 shows terminal missing/exited
4405 shows detached but recoverable
4406 shows transport unsupported and retries PTY
generic close remains generic failure
```

## Tests

```typescript
// remoteRunner.test.ts
test("control preferred when advertised", () => {
  expect(attachQuery({ transports: ["control", "pty"], readOnly: false }))
    .toBe("transport=control");
});
test("pty fallback when control absent", () => {
  expect(attachQuery({ transports: ["pty"], readOnly: true }))
    .toBe("transport=pty&read_only=true");
});
test("debug override wins", () => {
  expect(attachQuery({ transports: ["control"], debugOverride: "pty", readOnly: false }))
    .toBe("transport=pty");
});
test("close-code mapping matches T06 contract", () => {
  expect(stateFromAttachClose(4503)).toBe("runner_offline");
  expect(stateFromAttachClose(4404)).toBe("terminal_exited");
  expect(stateFromAttachClose(4405)).toBe("terminal_detached");
  expect(stateFromAttachClose(1006)).toBeNull();   // stays with existing retry logic
  expect(stateFromAttachClose(1011)).toBeNull();   // generic failure path
});
```

Plus a `TerminalSession` close-handler test asserting `4406` produces exactly
one PTY redial (spy on the WS factory) and `4503` produces zero redials.

Next: [step-03 — reconnect-aware terminal panel](step-03-reconnect-aware-terminal-panel.md)
