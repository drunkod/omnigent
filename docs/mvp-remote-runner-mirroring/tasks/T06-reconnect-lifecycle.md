# T06 — Reconnect semantics and terminal lifecycle states

Implements plan `02-server-runner-work-plan.md` Phase 5, `03-terminal-mirroring-ui-plan.md`
"Terminal reconnect semantics", and checklist P10 (state portion).

Ground truth (verified against current code):

- `create_runner_tunnel_router` already accepts `on_runner_connect` /
  `on_runner_disconnect` async callbacks (fired with `runner_id`); `server/app.py` wires
  them for liveness (`runner_online`).
- `TunnelRegistry.register` is newest-wins with generation guards; in-flight requests
  and WS channels on the old session are aborted with `ConnectionError` — so terminal
  attach channels die cleanly on reconnect and the browser must re-attach.
- `conversation_store.list_conversations_by_runner_id(runner_id)` exists for
  reconnect reconciliation.
- `SessionResourceRegistry` (runner) tracks `TerminalLifecycle` and publishes
  `TerminalExitEvent`s.

## 1. Terminal/runner state model — shared enum

New module `omnigent/entities/terminal_state.py` (imported by server routes and
emitted in session events so web/desktop UI can map states 1:1):

```python
"""Terminal + runner composite state for remote-local sessions.

The UI must be able to distinguish 'runner offline' (terminal state
unknown) from 'terminal exited' (runner online, process ended) from
'session stopped'. Plan 03 defines the vocabulary; this enum is the
single source of truth for those strings.
"""

from enum import Enum


class TerminalUiState(str, Enum):
    TERMINAL_UNKNOWN = "terminal_unknown"        # no resource yet
    TERMINAL_STARTING = "terminal_starting"      # runner creating terminal
    TERMINAL_RUNNING = "terminal_running"        # attachable
    TERMINAL_DETACHED = "terminal_detached"      # browser detached; tmux alive
    TERMINAL_EXITED = "terminal_exited"          # process ended
    RUNNER_OFFLINE = "runner_offline"            # tunnel down; terminal unknown
    RUNNER_RECONNECTED = "runner_reconnected"    # tunnel back; reconciling
    TERMINAL_RELAUNCHING = "terminal_relaunching"  # required terminal recreating
    TERMINAL_FAILED = "terminal_failed"          # launch/reconnect failed
```

## 2. Server: runner connect/disconnect fan-out to sessions

`omnigent/server/app.py` already passes liveness callbacks. Extend them to publish a
session event per bound conversation (SSE consumers get an immediate banner instead of
waiting for an attach failure):

```python
async def _on_runner_disconnect(runner_id: str) -> None:
    """Mark every session bound to this runner as runner_offline."""
    convs = await asyncio.to_thread(
        conversation_store.list_conversations_by_runner_id, runner_id
    )
    for conv in convs:
        _publish_session_event(conv.id, "session.runner_state", {
            "runner_id": runner_id,
            "state": TerminalUiState.RUNNER_OFFLINE.value,
        })


async def _on_runner_connect(runner_id: str) -> None:
    """Announce reconnect, then reconcile terminal resources per session."""
    convs = await asyncio.to_thread(
        conversation_store.list_conversations_by_runner_id, runner_id
    )
    for conv in convs:
        _publish_session_event(conv.id, "session.runner_state", {
            "runner_id": runner_id,
            "state": TerminalUiState.RUNNER_RECONNECTED.value,
        })
    # Reconciliation: ask the runner which session terminals are still
    # alive (tmux survives a tunnel drop — the runner process kept them).
    routed = _runner_client(runner_id)
    for conv in convs:
        try:
            resp = await routed.get(f"/v1/sessions/{conv.id}/resources/terminals")
        except Exception:
            continue  # runner flapped again; next connect retries
        for term in resp.json().get("data", []):
            state = (
                TerminalUiState.TERMINAL_RUNNING
                if term.get("running")
                else TerminalUiState.TERMINAL_EXITED
            )
            _publish_session_event(conv.id, "session.terminal_state", {
                "terminal_id": term["id"],
                "state": state.value,
            })
```

Keep the callback bounded — `on_runner_connect` already runs under a 30s
`asyncio.wait_for` in `runner_tunnel.py`; do the reconciliation loop with small
per-request timeouts so one dead session can't eat the budget.

## 3. Terminal attach close-code contract

`omnigent/server/routes/terminal_attach.py` already proxies attach through the tunnel.
Standardize close codes so the UI can map them to states (plan 03 asks for 4404/4405
tests):

```python
# terminal_attach.py — module-level contract, used by both proxy and local paths
ATTACH_CLOSE_RUNNER_OFFLINE = 4503      # runner tunnel down → RUNNER_OFFLINE
ATTACH_CLOSE_TERMINAL_NOT_FOUND = 4404  # no such terminal → TERMINAL_EXITED/UNKNOWN
ATTACH_CLOSE_TERMINAL_DETACHED = 4405   # tmux alive, PTY detached → TERMINAL_DETACHED
ATTACH_CLOSE_TRANSPORT_UNSUPPORTED = 4406  # transport=control not available → fall back to pty
```

In the attach handler, when `runner_ws_factory` raises `OmnigentError` with
`RUNNER_UNAVAILABLE`, close with `ATTACH_CLOSE_RUNNER_OFFLINE` and a human-readable
reason instead of a generic 1011:

```python
        try:
            runner_ws = await runner_ws_factory(session_id, path, query_string)
        except OmnigentError as exc:
            if exc.code is ErrorCode.RUNNER_UNAVAILABLE:
                await ws.close(code=ATTACH_CLOSE_RUNNER_OFFLINE,
                               reason="runner offline; reconnect the local runner")
                return
            raise
```

## 4. Runner: required-terminal relaunch on reconnect

Runner side, when a session's **required** terminal (lifecycle from
`SessionResourceRegistry._terminal_lifecycles`) is found dead at reconciliation time,
relaunch it in the bound workspace and publish `TERMINAL_RELAUNCHING` →
`TERMINAL_RUNNING`/`TERMINAL_FAILED`:

```python
async def reconcile_session_terminals(session_id: str) -> None:
    """Re-observe or relaunch required terminals after a tunnel reconnect."""
    registry: SessionResourceRegistry = app.state.session_resources
    for terminal_id, lifecycle in registry.lifecycles_for_session(session_id):
        alive = await registry.terminal_is_alive(session_id, terminal_id)
        if alive:
            continue
        if lifecycle is not TerminalLifecycle.REQUIRED:
            _publish_terminal_state(session_id, terminal_id, "terminal_exited")
            continue
        _publish_terminal_state(session_id, terminal_id, "terminal_relaunching")
        try:
            await registry.launch_required_terminal(session_id, terminal_id, ...)
            _publish_terminal_state(session_id, terminal_id, "terminal_running")
        except Exception:
            _publish_terminal_state(session_id, terminal_id, "terminal_failed")
```

(`lifecycles_for_session` / `terminal_is_alive` are thin accessors over existing
registry state — add them rather than reaching into privates.)

## 5. Tests

`tests/runner/test_terminal_attach_tunnel.py`:

```python
"""Attach through the tunnel: offline, reconnect, and close-code mapping."""


async def test_attach_offline_runner_closes_4503(app_client, tunnel_registry, bound_session):
    # bound_session fixture: conversation with runner_id set, runner NOT registered
    async with app_client.websocket_connect(
        f"/v1/sessions/{bound_session}/resources/terminals/terminal_agent/attach"
    ) as ws:
        closed = await ws.receive()
    assert closed["code"] == 4503


async def test_attach_unknown_terminal_closes_4404(app_client, online_runner, bound_session):
    async with app_client.websocket_connect(
        f"/v1/sessions/{bound_session}/resources/terminals/nope/attach"
    ) as ws:
        closed = await ws.receive()
    assert closed["code"] == 4404


async def test_reconnect_aborts_old_channels_and_preserves_binding(
    tunnel_registry, conversation_store, bound_session
):
    old = tunnel_registry.register("runner_test1", FakeWS(), make_hello())
    ch = tunnel_registry.open_ws_channel("runner_test1", "aabbccdd", session=old)
    new = tunnel_registry.register("runner_test1", FakeWS(), make_hello())
    # old channel got the abort sentinel; new session has no channels
    assert await ch.inbound_queue.get() is None
    assert new.ws_channels == {}
    # session affinity untouched by reconnect
    conv = conversation_store.get_conversation(bound_session)
    assert conv.runner_id == "runner_test1"


async def test_disconnect_publishes_runner_offline_event(server_with_events, online_runner):
    events = server_with_events.subscribe(bound_session)
    await online_runner.drop_tunnel()
    evt = await events.next("session.runner_state")
    assert evt["state"] == "runner_offline"


async def test_reconnect_publishes_reconciled_terminal_states(server_with_events, online_runner):
    await online_runner.drop_tunnel()
    await online_runner.reconnect()
    evt = await events.next("session.runner_state")
    assert evt["state"] == "runner_reconnected"
    term_evt = await events.next("session.terminal_state")
    assert term_evt["state"] in ("terminal_running", "terminal_exited")
```

## Acceptance checklist

- [ ] `TerminalUiState` enum shared by server events and (mirrored) UI types.
- [ ] Disconnect/connect callbacks publish `session.runner_state` per bound session.
- [ ] Reconnect reconciles terminals: alive → running, dead-required → relaunch,
      dead-auxiliary → exited.
- [ ] Attach close codes: 4503 offline / 4404 not-found / 4405 detached / 4406 transport.
- [ ] Newest-wins reconnect aborts old WS channels but never clears `conversations.runner_id`.
- [ ] Tests above pass, including simulated tunnel drop/reconnect.
