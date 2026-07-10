# Step 05 — Tests + manual QA gate

Required before calling T07 done. Most tests land inside steps 01–04's
commits; this file is the consolidated matrix and the manual QA script.

## 1. SSE parser tests — `web/src/lib/sse.test.ts`

`sse.ts` notes parser changes should add an SSE parser test; reducer tests
alone will not catch dropped event types.

```typescript
test("session.runner_state parses", () => {
  expect(parseSseEvent("session.runner_state", {
    conversation_id: "c1", runner_id: "r1", state: "runner_offline",
  })).toEqual({
    type: "session_runner_state", conversationId: "c1",
    runnerId: "r1", state: "runner_offline",
  });
});

test("session.terminal_state parses", () => {
  expect(parseSseEvent("session.terminal_state", {
    conversation_id: "c1", terminal_id: "t1", state: "terminal_relaunching",
  })).toMatchObject({ type: "session_terminal_state", state: "terminal_relaunching" });
});

test.each([
  ["missing conversation_id", { runner_id: "r1", state: "runner_offline" }],
  ["bad state value",         { conversation_id: "c1", runner_id: "r1", state: "exploded" }],
  ["runner state on terminal event", { conversation_id: "c1", terminal_id: "t1", state: "runner_offline" }],
])("malformed payload dropped: %s", (_name, data) => {
  expect(parseSseEvent("session.runner_state", data)).toBeNull();
});
```

## 2. Store transition tests — `terminalLifecycleStore.test.ts`

```text
runner_offline           -> offline banner state
runner_reconnected       -> reconciling state; stale terminal states cleared
terminal_relaunching     -> terminal_running (per-terminal, others untouched)
terminal_exited          -> exited state persists
wrong conversation id    -> other conversations' state unchanged
clearConversation        -> state dropped; selectors return defaults
```

(Snippets in [step-01](step-01-terminal-lifecycle-store.md).)

## 3. Attach client tests — `remoteRunner.test.ts` + `TerminalSession.test.ts`

```text
stateFromAttachClose: 4503, 4404, 4405, 4406, 1006->null, 1011->null
attachQuery: advertised control, legacy/missing PTY fallback, debug override, read_only
4406 close -> exactly one automatic pty redial from advertised control
legacy/unadvertised PTY + 4406 -> no redundant PTY-to-PTY redial
4503 close -> zero transport-loop redials (waits for lifecycle recovery)
1006 close -> existing transport-retry path unchanged
```

(Snippets in [step-02](step-02-attach-close-code-mapping.md).)

## 4. Component tests — offline/reconnect overlay

```text
existing buffer remains visible while offline
input disabled while offline, re-enabled on connected
reattach after terminal_running when previously open
refresh while offline -> runner_reconnected -> terminal_running also reattaches
detached panel shows a working Attach action, not failure styling
failed panel shows a working Retry action
overlay priority renders exactly one recovery message
exited panel shows exited UI, never an infinite spinner
```

(Snippets in [step-03](step-03-reconnect-aware-terminal-panel.md).)

## 5. Deferred Playwright e2e

The originally planned file,
`tests/e2e_ui/sessions/test_remote_local_runner.py`, is **not part of T07**.
The runner/host process orchestration needed for a stable CI fixture is deferred
to a follow-up test-infrastructure slice. Do not claim automated e2e coverage in
the PR.

The eventual Playwright scenario remains:

```text
create local-runner session       -> header shows "Local runner" badge
kill fake runner tunnel           -> offline banner appears; terminal overlay
                                     says session is preserved; buffer visible
reconnect runner                  -> banner clears; terminal repaints
                                     (assert prompt text still present in pane)
browser refresh while offline     -> lifecycle recovery reattaches after running
browser refresh mid-session       -> terminal reattaches to alive tmux terminal
```

Visual regression snapshots for the terminal panel and runner badge are also
deferred with that fixture.

## 6. Manual QA script and recorded evidence

```text
1. Start remote server.
2. Connect local runner (omnigent host --server <url>).
3. Create Codex-native local-runner session.
4. Confirm terminal opens in the workspace and print visible marker output.
5. Disconnect runner (kill process / drop network).
6. Confirm exactly one preserved-session overlay, buffer intact, input disabled.
7. Reconnect the host/runner; send a message when the architecture requires
   demand-driven runner relaunch.
8. Confirm runner relaunch/reconciliation and terminal reattach.
9. Refresh and confirm history remains available.
```

The T07 live walkthrough completed the disconnect leg: the buffer remained
visible, input was gated, and exactly one preserved-session message rendered.
After the host reconnected, sending a message launched the demand-driven runner;
refresh then showed the continued conversation. The PR Coverage section must
state that Playwright is deferred and include this manual walkthrough as the
evidence for the lifecycle gate.

## Done-when boundary (repeat of README)

```text
Backend lifecycle events from T06 produce visible, correct terminal UI states.
The terminal panel attaches through the existing resource WS route.
Advertised control transport is honored; legacy/missing transport metadata and
runtime `4406` fallback remain PTY-reachable.
Runner offline/reconnect does not look like a crash.
Terminal close codes become user-actionable UI states.
Core parser/store/component tests exist; live lifecycle QA is documented.
```
