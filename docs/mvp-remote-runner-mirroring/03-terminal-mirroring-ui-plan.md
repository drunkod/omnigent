# 03 — Terminal Mirroring and UI Plan

This file defines the terminal/UI work needed to make the remote/local runner MVP feel like the native AI terminal product. It is planning only.

## Core requirement

The UI must not loosely recreate a terminal. It must attach to the real runner-owned terminal session and stream terminal bytes/control frames accurately enough for native TUI agents.

Priority terminal behaviors:

- Real-time output.
- Cursor position.
- Colors and ANSI escape sequences.
- Alternate-screen applications.
- Full-screen TUI redraws.
- Resize.
- Mouse-mode reports.
- Paste.
- Ctrl/Alt/Escape sequences.
- Scrollback and copy/selection.
- Read-only observe mode.
- Interactive owner-only drive mode.
- Reconnect after network loss.

## Existing terminal stack to reuse

### `omnigent/server/routes/terminal_attach.py`

Existing route:

```text
WS /v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach
```

Why this matters:

- Already resource-addressed.
- Already runner-aware.
- Already proxies to runner WebSocket channel when runner factory is installed.
- Already supports `transport=control|pty`.
- Already enforces read-only vs owner-only interactive attach when permissions are enabled.

MVP task:

- Use this route as the only web terminal attach path.
- Do not add a second terminal protocol unless this route cannot support the MVP after testing.

### `omnigent/terminals/control_bridge.py`

Why this should be preferred:

- Uses `tmux -C` control mode.
- Streams raw pane bytes from `%output`.
- Seeds browser from `capture-pane -e -p`.
- Lets browser own grid, scrollback, selection, and copy.
- Injects input byte-exactly with hex `send-keys -H`.

MVP task:

- Make control bridge the default for local-runner web attach when available.
- Keep PTY bridge as fallback.
- Add test coverage that proves behavior does not regress.

### `omnigent/terminals/ws_bridge.py`

Why it still matters:

- It attaches through a real PTY using `tmux attach`.
- It preserves tmux-rendered full terminal UI.
- It may be closer for certain TUI overlays/popups.

MVP task:

- Keep PTY bridge available as `transport=pty`.
- Provide a UI/dev setting to switch transport for debugging.
- Use it as fallback when control mode cannot support an edge case.

### `omnigent/terminals/registry.py`

Why it matters:

- It is the authoritative registry of tmux terminal instances.
- It keys terminals by `(conversation_id, terminal_name, session_key)`.
- Multiple terminal sessions can exist inside one conversation.

MVP task:

- Keep this registry as the terminal lifecycle source of truth.
- Add metadata needed by UI: terminal role, transport, local/cloud backing, cwd label, command label, running/exited state.

## Terminal attach acceptance matrix

Create an implementation checklist and tests for the following:

| Case | Expected behavior |
| --- | --- |
| Basic shell prompt | Browser shows prompt and typed input echoes correctly. |
| Agent TUI startup | Native agent full-screen UI paints correctly. |
| Resize | Browser resize updates PTY/tmux dimensions and redraws correctly. |
| Alternate screen | Vim/agent full-screen app does not leak primary history. |
| Scrollback | Browser scrollback works in control mode for primary screen content. |
| Copy/select | Browser selection works without fighting tmux copy mode. |
| Paste | Multiline paste arrives byte-exactly and in order. |
| Ctrl-C | Interrupt reaches terminal process. |
| Esc/Alt | Escape-prefixed keys reach the process. |
| Mouse mode | Mouse reports pass through if terminal app enables them. |
| Read-only attach | Output visible; input dropped; tmux is attached read-only. |
| Non-owner attach | Non-owner can read only; cannot send raw input. |
| Runner disconnect | UI shows reconnecting/offline, not a blank crash. |
| Runner reconnect | UI reattaches or offers relaunch depending on terminal lifecycle. |
| Terminal exit | UI shows terminal exited with last status/output summary. |

## UI tasks

### Task UI-1 — Runner status panel

Target area:

- `web/src/*`
- session sidebar/status components

Required UI state:

- Runner online/offline.
- Runner version.
- Runner OS/arch.
- Supported harnesses.
- Supported terminal transports.
- Bound workspace label/path.
- Last seen.
- Reconnect state.

Acceptance criteria:

- Session header/sidebar clearly shows whether the agent is using local runner or managed/cloud execution.
- If runner is offline, UI explains how to reconnect and does not imply the session is lost.

### Task UI-2 — Workspace picker

Target area:

- new session modal/flow
- runner settings page

Requirements:

- List registered local runners owned by user.
- List approved workspace roots for selected runner.
- Validate workspace before creating session.
- Show warning if chosen harness is not available on selected runner.

Acceptance criteria:

- User can create a new local-runner session without CLI copy/paste after runner is paired.
- If no runner is online, UI shows setup instructions.

### Task UI-3 — Terminal panel improvements

Target area:

- terminal component using xterm.js
- session resource tab/panel

Requirements:

- Attach using existing resource terminal WebSocket.
- Pass `transport=control` by default for supported terminal roles.
- Allow debug override `transport=pty`.
- Show read-only badge when not owner.
- Show reconnecting state while runner tunnel is offline.
- Keep xterm buffer stable across reconnect where possible.

Acceptance criteria:

- Terminal opens automatically for native agent sessions.
- Terminal remains usable across browser refresh if runner/terminal are alive.

### Task UI-4 — Chat composer to native terminal injection

Context:

Some native terminal harnesses rely on bridge files/forwarders to inject web UI chat messages into the running TUI. Existing code already has bridge helpers for specific native harnesses.

Target areas:

- native bridge helpers such as `*_native_bridge.py`
- runner app auto-create flows
- web chat composer logic if mode-specific behavior is needed

Requirements:

- Composer input should reach the native terminal/harness in the same session.
- The transcript forwarder should mirror native replies back to Omnigent conversation history.
- If a harness does not support safe injection/mirroring, UI should show terminal-only mode or unsupported status.

Acceptance criteria:

- At least Codex-native and one additional native terminal demonstrate chat-to-terminal and terminal-to-chat round trip.

### Task UI-5 — Diff and command review surfaces

Target areas:

- approval cards
- diff viewer
- session event stream

Requirements:

- File writes show diff preview before execution in manual/assisted modes.
- Shell commands show command, cwd, environment summary, risk level, and reason for approval.
- Completed actions show status, duration, exit code, and compact output.

Acceptance criteria:

- User can tell exactly what will happen locally before approving.
- Every side-effectful local action has an event trail.

## Terminal reconnect semantics

Define these states explicitly in API/UI:

```text
terminal_unknown       # no resource yet
terminal_starting      # runner creating terminal
terminal_running       # attachable
terminal_detached      # browser detached; tmux session still alive
terminal_exited        # process ended
runner_offline         # runner tunnel down; terminal state unknown
runner_reconnected     # runner returned; resources being reconciled
terminal_relaunching   # required terminal is being recreated
terminal_failed        # launch/reconnect failed
```

Implementation tasks:

- Add state mapping in runner resource registry or session events.
- Ensure terminal attach close codes map to UI states.
- Add tests for `4404` terminal-not-found and `4405` detached handling where applicable.

## Terminal transport decision

Recommended default order:

1. `control` for browser-owned scrollback/selection and byte-level pane output.
2. `pty` when exact tmux-rendered overlays/status/copy mode are required.
3. read-only variants for observers/non-owners.

Implementation notes:

- Keep the server query param `transport` as an explicit override.
- Store last chosen transport per user/session only after MVP if needed.
- Add debug logging for resolved transport in both server and runner.

## UI testing tasks

Add e2e or integration tests for:

- New session with local runner selected.
- Terminal attach through runner tunnel.
- Read-only attach for non-owner.
- Terminal reconnect after browser refresh.
- Runner offline banner.
- Approval prompt for local command.
- Diff preview before file write.

Visual regression tests:

- Basic terminal panel.
- Runner offline state.
- Approval card.
- Workspace picker.

## Manual QA script

Use this as a human acceptance script once implementation exists:

1. Start remote server.
2. Start local runner and pair it with server.
3. Register workspace `~/projects/demo`.
4. Create Codex-native session in local-runner mode.
5. Confirm terminal opens in browser and cwd is the workspace.
6. Type into terminal; confirm input reaches native TUI.
7. Ask agent to inspect a file.
8. Approve a read/write action.
9. Confirm diff appears before write.
10. Run tests through shell command approval.
11. Disconnect runner network.
12. Confirm UI shows runner offline.
13. Reconnect runner.
14. Confirm session can continue or terminal relaunch is offered.
