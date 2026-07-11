# T06b Step 01 — Runner-state snapshot on SSE connect

Track 3, step 1. Problem (from the T07 review): a page refreshed during a
long runner-offline period gets an empty lifecycle store — the web store
defaults to "online" until the next live `session_runner_state` event, so
the preserved-session copy is missing exactly when it matters.

Key discovery that shrinks this task: the events stream **already supports
snapshot-on-connect** — `_session_event_stream` (sessions.py ~L11515) takes
an `on_subscribed` hook whose events are yielded ahead of the live tail.
Presence already uses it. This step is: track last runner state per
session, replay it through that hook.

## 1. Track last runner state where it's published

`session_runner_state` events are produced in
`omnigent/server/routes/runner_tunnel.py` (tunnel connect/disconnect).
Add a tiny module-level registry:

```python
# omnigent/server/_runner_state_registry.py
"""Last-known runner lifecycle state per session, for SSE replay.

Written by the runner tunnel route whenever it publishes a
``session_runner_state`` event; read by the session events stream's
snapshot-on-connect hook so a fresh subscriber immediately learns the
runner is offline instead of assuming online.
"""

from __future__ import annotations

# session_id → last published session_runner_state event dict
_last_runner_state: dict[str, dict[str, object]] = {}


def record(session_id: str, event: dict[str, object]) -> None:
    _last_runner_state[session_id] = event


def snapshot(session_id: str) -> dict[str, object] | None:
    return _last_runner_state.get(session_id)


def clear(session_id: str) -> None:
    """Call on session deletion; offline entries are otherwise retained
    deliberately — a refresh during a week-long offline period is the
    whole point."""

    _last_runner_state.pop(session_id, None)


def reset_for_tests() -> None:
    _last_runner_state.clear()
```

At each `session_stream.publish(session_id, event)` of a
`session_runner_state` event in `runner_tunnel.py`:

```python
from omnigent.server import _runner_state_registry

_runner_state_registry.record(session_id, event)
session_stream.publish(session_id, event)
```

(If the tunnel route fans one runner state out to many bound sessions,
record per session inside that loop.)

## 2. Replay via `on_subscribed`

In the events route that builds `_session_event_stream`, extend (or add)
the `on_subscribed` hook:

```python
def _runner_state_snapshot() -> list[dict[str, object]]:
    snap = _runner_state_registry.snapshot(session_id)
    return [snap] if snap is not None else []
```

Compose with the existing hook if the route already passes one (presence):
yield presence snapshot events first, then the runner state. Only replay
**offline-ish** states if you want to minimize noise — replaying
`runner_running` is harmless but redundant:

```python
snap = _runner_state_registry.snapshot(session_id)
if snap is not None and snap.get("state") != "terminal_running_ok":
    events.append(snap)
```

## 3. Web store — no changes needed (verify)

`terminalLifecycleStore.applyRunnerState` already handles
`session_runner_state` (store L36); the chat SSE dispatcher routes the
type (chatStore.ts ~L4280). A replayed event is indistinguishable from a
live one, so the T07 refresh-while-offline arming path
(`runner_offline` → pending reattach on `terminal_running`) fires exactly
as in the live case. Add one store test:

```typescript
it("seeds offline state from a snapshot event before any live event", () => {
  useTerminalLifecycleStore.getState().applyRunnerState({
    type: "session_runner_state",
    conversationId: "conv_a",
    state: "runner_offline",
  });
  expect(
    useTerminalLifecycleStore.getState().runnerState("conv_a"),
  ).toBe("runner_offline");
});
```

## 4. Server tests

```python
# tests/server/test_runner_state_snapshot.py
from omnigent.server import _runner_state_registry


def test_record_and_snapshot_roundtrip() -> None:
    _runner_state_registry.reset_for_tests()
    event = {"type": "session_runner_state", "state": "runner_offline"}
    _runner_state_registry.record("conv_a", event)
    assert _runner_state_registry.snapshot("conv_a") == event
    assert _runner_state_registry.snapshot("conv_b") is None


async def test_sse_replays_offline_state_to_fresh_subscriber(
    client, seeded_session_with_offline_runner
) -> None:
    session_id = await seeded_session_with_offline_runner()
    async with client.stream("GET", f"/v1/sessions/{session_id}/events") as resp:
        first_events = await _read_events(resp, count=3)  # ready, snapshot, …
    assert any(
        e.get("type") == "session_runner_state" and e.get("state") == "runner_offline"
        for e in first_events
    )
```

## Done when

- A browser refresh during runner-offline immediately shows the
  preserved-session overlay (no generic UI), verified live.
- Snapshot replays only through `on_subscribed` — no polling endpoint.
- Recovery still single-fires on `terminal_running` (existing T07 tests
  keep passing).
