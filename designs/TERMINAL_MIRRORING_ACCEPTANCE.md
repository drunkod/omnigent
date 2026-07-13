# Terminal Mirroring Acceptance

This ledger maps the T12 terminal contract to executable evidence. A requirement is
covered only when the named test crosses the required live boundary. Unit and
component tests are listed as supporting evidence, not substitutes for live coverage.

## Fixture boundary

The tests in `tests/terminal_e2e/test_control_attach.py` traverse an authenticated
WebSocket client, the public server attach route, the multiplexed runner tunnel, the
runner attach route, and a real tmux pane. The fixture uses deterministic content and
fails when tmux is unavailable.

An aborted tunnel channel intentionally synthesizes WebSocket close code `1006`; the
public attach route interprets that abnormal close as runner loss (`4503`). This is a
transport heuristic, not a claim that every possible runner-side bridge crash is a
cleanly diagnosed offline event. Clean terminal exits retain their explicit `4404` code.

## Byte behavior

| Requirement | Status | Evidence |
| --- | --- | --- |
| Control attach and input round trip | Covered | `test_control_attach_initial_capture_and_input_round_trip` |
| Initial capture appears once | Covered | `test_control_attach_initial_capture_and_input_round_trip` |
| Resize reaches the pane process | Covered | `test_resize_reaches_terminal_process` |
| Large multiline paste arrives once and in order | Covered | `test_multiline_utf8_paste_arrives_once_and_in_order` |
| UTF-8 and wide characters survive | Covered | `test_multiline_utf8_paste_arrives_once_and_in_order` |
| Read-only output with no input side effect | Covered | `test_read_only_collaborator_observes_but_cannot_drive_terminal` |
| Single canonical line of 4 KiB or larger | Not guaranteed | The supported large-paste proof uses bounded lines to respect the host terminal's `MAX_CANON` limit. |
| PTY transport parity | Pending product decision | Required only if PTY remains a supported platform contract. |
| Unsupported transport closes without destroying runner/tmux state | Covered | `test_unsupported_transport_closes_without_disturbing_runner_or_tmux` |
| Ctrl-C interrupts the foreground process | Covered | `test_ctrl_c_interrupts_foreground_process` |
| ESC, arrows, tab, backspace, and Enter | Covered | `test_control_key_sequences_arrive_byte_exact` |
| Alternate-screen enter and exit | Covered | `test_alternate_screen_enter_and_exit_bytes_are_forwarded` |
| Rapid output remains ordered and bounded | Covered | `test_rapid_output_remains_ordered_and_bounded` |

## Authorization and lifecycle

| Requirement | Status | Evidence |
| --- | --- | --- |
| Collaborator interactive attach is rejected before runner proxy | Covered | `test_read_collaborator_cannot_open_interactive_attach` |
| Collaborator read-only attach receives output | Covered | `test_read_only_collaborator_observes_but_cannot_drive_terminal` |
| Runner offline differs from terminal exit | Covered | `test_runner_tunnel_drop_closes_attach_as_runner_offline`; `test_terminal_exit_closes_attach_as_terminal_exited` |
| Same-runner reconnect avoids duplicate output and input | Covered | `test_same_runner_reconnect_reattaches_without_duplicate_io` |
| Panel remount while offline preserves state and reattaches after recovery | Covered | `test_preserves_runner_offline_state_across_a_panel_remount_and_reattaches_after_recovery` |
| Full browser reload while offline restores preserved-session state | Pending browser E2E | Requires a real page reload/SSE bootstrap fixture; component/store evidence is not promoted to live coverage. |
| Unsupported transport performs one control-to-PTY fallback and does not loop | Covered | `test_unsupported_transport_closes_without_disturbing_runner_or_tmux`; `falls back from control to PTY once and stops on a second unsupported close` |
| Stale lifecycle state cannot cover a connected terminal | Covered | `test_stale_generation_close_cannot_cover_live_reconnected_terminal` |
| Reconnect during approval is at most once | Covered | `test_pending_local_action_executes_once_after_runner_tunnel_reconnect` |

## Required CI gates

| Gate | Status | Scope |
| --- | --- | --- |
| `terminal-e2e-control` | Active | Public route, control transport, real tmux |
| `terminal-e2e-pty` | Pending product decision | Required only if PTY is part of the supported platform contract |
| `terminal-e2e-reconnect` | Active | Runner generation, stale lifecycle, approval reconnect, transport capability checks, and browser remount recovery |
