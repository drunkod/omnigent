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
attachQuery: control default, pty fallback, debug override, read_only
4406 close -> exactly one automatic pty redial
4503 close -> zero redials (waits for lifecycle event)
1006 close -> existing transport-retry path unchanged
```

(Snippets in [step-02](step-02-attach-close-code-mapping.md).)

## 4. Component tests — offline/reconnect overlay

```text
existing buffer remains visible while offline
input disabled while offline, re-enabled on open
reattach attempted after terminal_running (only if previously open)
exited panel shows exited UI, never an infinite spinner
detached panel shows attach action, not failure styling
```

(Snippets in [step-03](step-03-reconnect-aware-terminal-panel.md).)

## 5. Playwright e2e — `tests/e2e_ui/sessions/test_remote_local_runner.py`

Plan 03 testing targets: terminal attach through runner tunnel, browser
refresh reconnect, runner offline banner, terminal reconnect after refresh.

```text
create local-runner session       -> header shows "Local runner" badge
kill fake runner tunnel           -> offline banner appears; terminal overlay
                                     says session is preserved; buffer visible
reconnect runner                  -> banner clears; terminal repaints
                                     (assert prompt text still present in pane)
browser refresh mid-session       -> terminal reattaches to alive tmux terminal
```

Visual regression snapshots: terminal panel (normal + offline overlay),
runner badge (online/offline/reconnecting).

## 6. Manual QA script (from the plan)

```text
1. Start remote server.
2. Connect local runner (omnigent host --server <url>).
3. Create Codex-native local-runner session.
4. Confirm terminal opens in the workspace.
5. Disconnect runner (kill process / drop network).
6. See offline UI: banner + overlay, buffer intact, input disabled.
7. Reconnect runner.
8. Confirm session continues or terminal relaunch is offered;
   relaunching -> running transition visible.
```

## Done-when boundary (repeat of README)

```text
Backend lifecycle events from T06 produce visible, correct terminal UI states.
The terminal panel attaches through the existing resource WS route.
Control transport is the default; PTY fallback is reachable.
Runner offline/reconnect does not look like a crash.
Terminal close codes become user-actionable UI states.
Core parser/store/component tests exist.
```
