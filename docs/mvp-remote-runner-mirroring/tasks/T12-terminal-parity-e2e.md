# T12 — Real terminal parity and reconnect E2E

T12 is a Stage 2 track. Its fixture may start after T10 step 01 freezes session creation
and runner/workspace binding. It can then proceed in parallel with T09 and T11.

Existing unit tests around `TerminalSession`, lifecycle stores, close-code mapping, and
route authorization are useful but do not prove native tmux/xterm byte behavior. T12
adds that missing acceptance layer.

## Goal

A browser attached through the Omnigent server and runner tunnel behaves like a real
terminal for the supported MVP transport, and reconnect/failure states preserve the
session contract without duplicate input or misleading overlays.

## Step 01 — Deterministic real fixture

Build a test fixture that starts:

- Omnigent server with the local-runner feature enabled;
- an authenticated owner and optional collaborator;
- a real runner tunnel with one approved temporary workspace;
- a real tmux session and deterministic shell program;
- the web app/browser test client.

Use the canonical T10 API to discover the runner and create the session with
`runner_id + workspace_id`. Do not inject a raw workspace path into the browser create
request.

The fixture must expose controls to:

- stop/restart the runner tunnel;
- kill only the tmux pane/session;
- delay or drop frames;
- resize the browser terminal;
- inspect shell-received bytes and terminal output;
- create owner/read-only collaborator clients.

Keep platform-specific prerequisites explicit. If the CI image lacks tmux/PTY support,
provide a named required Linux job rather than silently skipping the acceptance suite.

## Step 02 — Byte and terminal behavior

Required cases:

- control-mode attach round trip;
- PTY attach when selected/supported and deterministic unsupported close behavior;
- initial capture-pane/history appears once;
- resize reaches the tmux/PTY process and applications observe new rows/columns;
- multiline and large paste arrives once and in order;
- UTF-8 and wide characters survive round trip;
- Ctrl-C interrupts the foreground process;
- ESC, arrows, tab, backspace, and Enter preserve expected byte sequences;
- alternate-screen enter/exit returns to the prior screen correctly;
- rapid output remains ordered and bounded;
- read-only attach receives output and cannot send input.

Use deterministic shell helpers rather than asserting against a human-oriented prompt.
Record enough diagnostics to debug a failed byte assertion without logging secrets.

## Step 03 — Lifecycle and reconnect behavior

Required cases:

1. runner tunnel drops during active output → one runner-offline state, session and
   transcript preserved;
2. runner reconnects with the same binding → terminal reattaches without duplicated
   initial output or input;
3. browser refresh while runner is offline → preserved-session copy appears from the
   snapshot and recovers after reconnect;
4. terminal exits while runner remains online → terminal-exited state, not
   runner-offline;
5. attach transport unsupported → stable close code/copy and no retry loop;
6. collaborator interactive attach → denied before the runner proxy;
7. collaborator read-only attach → output works, input is disabled server- and
   client-side;
8. stale lifecycle event after a successful reconnect cannot cover a live terminal;
9. reconnect during a pending local-action approval does not execute or resolve the
   action twice.

## CI gates

Create named jobs suitable for branch protection:

- `terminal-e2e-control`
- `terminal-e2e-pty` when PTY support is part of the platform contract
- `terminal-e2e-reconnect`

The job summary should report server version, runner version, selected transport, tmux
version, and close code on failure, while omitting tokens, commands, workspace roots,
and terminal contents unless the fixture uses non-sensitive deterministic text.

## Done when

- tests traverse browser → server attach route → runner tunnel → real tmux/PTY;
- resize, paste, UTF-8, control keys, and alternate-screen behavior are covered;
- terminal exit and runner offline are distinguished at the live boundary;
- refresh and reconnect do not duplicate bytes, input, or approval execution;
- required CI jobs run rather than skip on the supported platform; and
- `designs/TERMINAL_MIRRORING_ACCEPTANCE.md` links each acceptance requirement to a
  named test.
