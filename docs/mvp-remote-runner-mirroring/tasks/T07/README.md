# T07 — Terminal lifecycle UI + attach/reconnect UX

T07 is the **UI/UX consumption layer for T06's lifecycle work**, not another
backend-heavy reconnect task.

T06 delivered the backend contract: shared terminal states, server runner-state
fan-out, runner-side terminal reconciliation, attach close codes, and TS parsing.
The gap: `web/src/lib/sse.ts` already **parses** `session.runner_state` /
`session.terminal_state`, but `chatStore.ts` (case `session_runner_state` /
`session_terminal_state`, ~line 4274) accepts and **ignores** them.

User-facing goal: when the runner disconnects, reconnects, relaunches a required
terminal, or loses a terminal, the UI shows the right state and recovery action
instead of looking like a generic WebSocket failure.

## Steps

| Step | Slice (≈ one commit each) | Files |
| --- | --- | --- |
| [step-01](step-01-terminal-lifecycle-store.md) | Terminal lifecycle store + event plumbing | `terminalLifecycleStore.ts`, `chatStore.ts`, sse/store tests |
| [step-02](step-02-attach-close-code-mapping.md) | Attach close-code → UI state mapping, transport default + PTY fallback | `TerminalSession.ts`, `remoteRunner.ts`, tests |
| [step-03](step-03-reconnect-aware-terminal-panel.md) | Reconnect-aware terminal panel (buffer stability, auto-reattach) | `MainTerminalView.tsx`, `TerminalsPanel.tsx`, `useTerminalStatuses.ts` |
| [step-04](step-04-runner-status-banner.md) | Minimal runner/session status banner | `ChatHeader.tsx` / sidebar |
| [step-05](step-05-tests-and-manual-qa.md) | Required tests + manual QA gate | test files across the above |
| [step-06](step-06-deferred-scope.md) | Deferred: workspace picker, approval/diff cards | — (not in this PR) |

## Ground truth (verified against current code)

- `web/src/components/blocks/TerminalSession.ts` already implements the xterm ↔
  attach-WebSocket bridge with `transport=control|pty`, close-code classification
  (`isUnexpectedTerminalClose`: 1001/1006/1012/1013 are transport-shaped), resize,
  CSI-u synthesis. **Extend it — do not write a new terminal protocol.**
- `web/src/lib/events.ts` already defines `TerminalUiState`,
  `SessionRunnerStateEvent`, `SessionTerminalStateEvent`.
- `web/src/lib/sse.ts` already validates and emits both lifecycle events.
- `web/src/store/terminalActivity.ts` is the zustand pattern to follow for the
  new lifecycle store.
- `web/src/hooks/RunnerHealthProvider.tsx` already exposes per-session
  runner-online maps — reuse for the banner, don't add a poller.
- Attach close codes from T06: `4503` runner offline, `4404` terminal not found,
  `4405` detached, `4406` unsupported transport.

## Done when

```text
Backend lifecycle events from T06 produce visible, correct terminal UI states.
The terminal panel attaches through the existing resource WS route.
Control transport is the default; PTY fallback is reachable.
Runner offline/reconnect does not look like a crash.
Terminal close codes become user-actionable UI states.
Core parser/store/component tests exist.
```

## Explicitly out of scope (see step-06)

Full workspace picker, full runner capability dashboard, and approval/diff UX.
They touch session creation, runner discovery, and local-action policy —
separate slices (T07b/T09 and the T05/T08 permissions work).
