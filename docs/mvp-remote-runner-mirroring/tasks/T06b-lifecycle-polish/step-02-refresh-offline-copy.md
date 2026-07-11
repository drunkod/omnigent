# T06b Step 02 — Refresh-while-offline UI copy on cold mount

Track 3, step 2. Depends on step 01 (the snapshot event is what makes the
cold-mount store non-empty). With the snapshot landing, most of the UI
already works — the T07 overlay chain renders the runner-offline branch
from `lifecycleTerminalState`/`runnerState`. This step is copy + polish,
plus a regression test for the exact cold-mount sequence.

## 1. Verify the overlay branch on cold mount

`TerminalView.tsx` (~L555 and ~L622) already renders:

```
Runner offline. Session is preserved; restart the runner to continue.
```

With step 01, a cold mount receives `runner_offline` before the attach
attempt resolves, so `StatusOverlay` should pick the runner branch (top
priority in the chain) rather than the generic connecting/failed states.
Trace the actual first-render order: if the attach's `4503` close races
ahead of the SSE snapshot, both paths now converge on the same overlay —
assert that only one preserved-session message renders (T07's earlier
double-message bug class).

## 2. Cold-mount regression test

```typescript
// TerminalView.lifecycle.test.tsx
it("shows preserved-session copy on a cold mount into an offline runner", async () => {
  // Snapshot arrives before any bridge state (step-01 replay order).
  act(() => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      state: "runner_offline",
    });
  });
  render(<TerminalView conversationId="conv_abc" terminalId="terminal_bash_s1" />);

  const messages = await screen.findAllByText(/Session is preserved/);
  expect(messages).toHaveLength(1);

  // Recovery: runner returns, exactly one reattach.
  act(() => {
    useTerminalLifecycleStore.getState().applyRunnerState({
      type: "session_runner_state",
      conversationId: "conv_abc",
      state: "runner_reconnected",
    });
    useTerminalLifecycleStore.getState().applyTerminalState({
      type: "session_terminal_state",
      conversationId: "conv_abc",
      terminalId: "terminal_bash_s1",
      state: "terminal_running",
    });
  });
  await waitFor(() => expect(terminalSessionMock.instances).toHaveLength(2));
});
```

Mirror the existing `renderAndAttach` helper's mock setup; the key
difference from the existing refresh test is that here the store is
seeded **before** first render (snapshot semantics), not after.

## 3. Badge copy consistency

`RunnerStatusBadge` (web/src/shell/RunnerStatusBadge.tsx) already says
"Session is preserved and will recover when the runner returns." Confirm
the badge also renders on cold mount (it reads the same store), and that
the header + terminal overlay don't disagree on wording. Single source:
if copy is duplicated in three places, extract:

```typescript
// web/src/lib/runnerCopy.ts
export const RUNNER_OFFLINE_PRESERVED =
  "Runner offline. Session is preserved; restart the runner to continue.";
export const RUNNER_OFFLINE_BADGE_TITLE =
  "Session is preserved while the runner is offline";
```

## Done when

- Cold mount into an offline runner shows the preserved-session overlay
  and badge immediately (live QA: kill runner → refresh page).
- Exactly one preserved-session message (regression test above).
- Recovery from cold mount reattaches once on `terminal_running`.
