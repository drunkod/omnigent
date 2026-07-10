# Step 03 — Reconnect-aware terminal panel

**Commit 3 of T07.** Combine step-01's lifecycle store and step-02's close
mapping into panel behavior: offline never looks like a crash, reconnect
reattaches, terminal state maps to a specific overlay.

## Files

```text
web/src/shell/MainTerminalView.tsx
web/src/shell/TerminalsPanel.tsx
web/src/shell/useTerminalStatuses.ts
web/src/components/blocks/TerminalSession.ts (overlay hooks only — bridge done in step-02)
```

## Behavior contract

| Event/state | UI behavior |
| --- | --- |
| `runner_offline` | Offline banner; disable terminal input; **keep existing xterm buffer visible**. |
| `runner_reconnected` | "Reconnected, checking terminals…" until per-terminal states arrive. |
| `terminal_relaunching` | Spinner/overlay on that terminal only. |
| `terminal_running` | Enable attach/re-attach; clear relaunching/offline overlay. |
| `terminal_exited` | Exited state; keep last visible buffer; offer refresh/reopen if supported; **never spins forever**. |
| `terminal_failed` | Failure state with retry/reconnect guidance. |
| `terminal_detached` | Browser detached but tmux alive: show attach button, **not** failure styling. |

## Task

### 1. Derive panel status from both signal sources

`useTerminalStatuses` already merges resource lifetime + bridge
`ConnectionState` + activity pulses. Add the lifecycle store as a third input:

```typescript
// useTerminalStatuses.ts (sketch)
const lifecycle = useTerminalLifecycleStore(
  useShallow((s) => s.byConversation[conversationId] ?? null),
);

function panelStatusFor(terminalId: string): TerminalPanelStatus {
  // Runner-level state wins: an offline runner overrides whatever the
  // per-terminal bridge last saw.
  if (lifecycle?.runnerState === "runner_offline") return { kind: "runner_offline" };
  if (lifecycle?.runnerState === "runner_reconnected") return { kind: "reconciling" };

  const ts = lifecycle?.terminalStateById[terminalId] ?? "terminal_unknown";
  switch (ts) {
    case "terminal_relaunching": return { kind: "relaunching" };
    case "terminal_exited":      return { kind: "exited" };
    case "terminal_failed":      return { kind: "failed" };
    case "terminal_detached":    return { kind: "detached" };
    default:
      // terminal_unknown/starting/running -> fall through to the
      // existing bridge ConnectionState-derived status.
      return statusFromConnectionState(connectionStates.get(terminalId));
  }
}
```

### 2. Buffer stability across reconnect

Keep the xterm instance **mounted** while showing the offline/reconnecting
overlay — never unmount/remount on `runner_offline`:

```tsx
// MainTerminalView.tsx (sketch)
<div className="terminal-panel">
  <TerminalHost session={terminalSession} />   {/* always mounted */}
  {status.kind === "runner_offline" && (
    <TerminalOverlay tone="warning">
      Local runner offline — session is preserved.
      <span className="overlay-hint">
        Restart the runner to continue. Your terminal history stays here.
      </span>
    </TerminalOverlay>
  )}
  {status.kind === "reconciling" && (
    <TerminalOverlay tone="info" spinner>Reconnected, checking terminals…</TerminalOverlay>
  )}
  {status.kind === "relaunching" && (
    <TerminalOverlay tone="info" spinner>Relaunching terminal…</TerminalOverlay>
  )}
  {status.kind === "detached" && (
    <TerminalOverlay tone="neutral" action={{ label: "Attach", onClick: reattach }}>
      Terminal detached — session still running.
    </TerminalOverlay>
  )}
  {status.kind === "exited" && (
    <TerminalOverlay tone="neutral">Terminal exited.</TerminalOverlay>
  )}
  {status.kind === "failed" && (
    <TerminalOverlay tone="error" action={{ label: "Retry", onClick: reattach }}>
      Terminal failed to start.
    </TerminalOverlay>
  )}
</div>
```

While offline, also gate input: `term.options.disableStdin = true` (restore on
`connected`). Control-mode re-attach re-seeds from `capture-pane` server-side, so
history repaints without clearing the buffer.

### 3. Auto-reattach policy

```text
Runner offline:
  do NOT redial the terminal WS in a loop;
  wait for runnerState === "runner_reconnected"/"online" or user action.
Terminal running after reconnect:
  reattach automatically IF this panel was already open before the disconnect.
Terminal exited/failed:
  stop reconnecting; show state-specific UI.
Browser refresh:
  normal mount flow attaches to the alive tmux terminal (existing route).
```

Implementation sketch — a `wasAttachedRef` per panel:

```typescript
const wasAttachedRef = useRef(false);
useEffect(() => {
  if (bridgeState.kind === "connected") wasAttachedRef.current = true;
  if (bridgeState.kind === "runner_offline") { /* keep flag: we were attached */ }
}, [bridgeState]);

// Reattach exactly once when the terminal comes back and we were attached before.
useEffect(() => {
  if (terminalState === "terminal_running" && wasAttachedRef.current
      && bridgeState.kind !== "connected" && bridgeState.kind !== "connecting") {
    reattach();
  }
}, [terminalState]);
```

Guard `reattach()` with the conversation id (stale-closure check) the same way
`TerminalSession` scopes listeners with an `AbortController`.

### 4. Read-only badge

When the viewer isn't the owner, pass `readOnly: true` into `attachQuery`
(step-02) and render a "view only" chip. Permission enforcement is unchanged —
`terminal_attach.py` already enforces it server-side.

## Acceptance

```text
when runner goes offline, terminal buffer stays visible but input is disabled
when runner reconnects, previously-open terminal panel reattaches
when required terminal relaunches, panel shows relaunching then running
when terminal exits, panel does not spin forever
browser refresh reattaches to alive terminal
```

## Tests

Component test (vitest + testing-library) for the overlay states:

```typescript
it("offline keeps buffer, disables input", async () => {
  renderPanel({ bufferText: "hello from tmux" });
  actLifecycle({ state: "runner_offline" });
  expect(screen.getByText(/runner offline/i)).toBeInTheDocument();
  expect(screen.getByText("hello from tmux")).toBeInTheDocument(); // buffer intact
  expect(termMock.options.disableStdin).toBe(true);
});

it("reattaches after terminal_running when previously open", async () => {
  renderPanel(); await attachOnce();
  actLifecycle({ state: "runner_offline" });
  actLifecycle({ state: "runner_reconnected" });
  actTerminal("t1", "terminal_relaunching");
  actTerminal("t1", "terminal_running");
  expect(wsFactory).toHaveBeenCalledTimes(2);   // exactly one redial
});
```

Next: [step-04 — runner status banner](step-04-runner-status-banner.md)
