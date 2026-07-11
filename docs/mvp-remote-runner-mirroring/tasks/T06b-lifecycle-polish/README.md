# T06b — Lifecycle polish (Track 3 steps)

Closes the one T06 follow-up from the T07 review: a page refreshed during
a long runner-offline period shows generic UI because the lifecycle store
starts empty. Key simplification discovered during grounding: the session
events stream already supports snapshot-on-connect via the
`on_subscribed` hook (`sessions.py` ~L11515, used by presence) — no new
endpoint or polling needed.

Steps are sequential (02 depends on 01's replayed event). The track is
server-then-web and independent of T08 close-out and T09.

1. `step-01-runner-snapshot-on-connect.md` — track last
   `session_runner_state` per session at the tunnel route, replay it via
   `on_subscribed` to fresh subscribers.
2. `step-02-refresh-offline-copy.md` — cold-mount regression test for the
   preserved-session overlay, single-message assertion, copy
   consolidation across overlay + badge.

Done-when for the track: kill the runner, refresh the browser — the
preserved-session overlay and badge render immediately (not after a
failed attach), exactly one message, and recovery reattaches once when
the runner returns.
