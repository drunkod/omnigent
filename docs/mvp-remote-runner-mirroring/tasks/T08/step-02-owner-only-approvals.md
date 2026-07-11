# Step 02 — Owner-only approval of local actions

Goal: only the session **owner** may approve or deny a local machine
action; collaborators may watch. Enforced server-side at the approval
resolution path — never in the UI, never runner-side.

## How local-action approvals flow today (verified)

1. Runner gateway hits an ASK verdict →
   `omnigent/runner/app.py::_request_local_action_approval` POSTs a
   `mcp_elicitation` event whose `data` carries `kind`, `policy_mode`,
   `cwd`, `path_summary`/`command_summary`, `risk_flags`.
2. The server mints `elicitation_id = f"elicit_{secrets.token_hex(16)}"`
   (`sessions.py` ~L1493) and records
   `_harness_elicitation_owners[elicitation_id] = session_id` (~L1508).
3. The UI answers by POSTing an approval event; the handler around
   `sessions.py` L4020 resolves the parked Future and calls
   `_forward_approval_to_runner` (L3924).
4. The runner's `pending_approvals.resolve` completes the gate.

There is currently **no user-level check** in step 3 beyond session access
— any collaborator who can post session events can approve. That's the gap.

## 1. Tag local-action elicitations at mint time

Where the server mints the elicitation id for an incoming
`mcp_elicitation` event, detect the local-action shape and remember it:

```python
# sessions.py — module scope, next to _harness_elicitation_owners
# elicitation_id → session_id for elicitations that gate a LOCAL machine
# action (write/shell on the user's computer). Entries are pruned in the
# same finally blocks that pop _harness_elicitation_owners.
_local_action_elicitations: dict[str, str] = {}


def _is_local_action_elicitation(data: Mapping[str, Any]) -> bool:
    """A runner local-action gate carries the audit fields; harness
    elicitations (MCP tools) don't."""
    return isinstance(data.get("policy_mode"), str) and isinstance(
        data.get("kind"), str
    )
```

At the mint site (~L1493–1508), after registering the owner:

```python
if _is_local_action_elicitation(event_data):
    _local_action_elicitations[elicitation_id] = session_id
```

Prune wherever `_harness_elicitation_owners.pop(elicitation_id, None)` runs
(~L1581):

```python
_local_action_elicitations.pop(elicitation_id, None)
```

## 2. Enforce at resolution

In the approval-resolution handler (before the Future is resolved and
before `_forward_approval_to_runner` at the end, ~L4070):

```python
from omnigent.server.routes._auth_helpers import get_session_owner_id

elicitation_id = data.get("elicitation_id", "")
if (
    isinstance(elicitation_id, str)
    and _local_action_elicitations.get(elicitation_id) == session_id
):
    owner_id = get_session_owner_id(permission_store, session_id)
    if user_id is None or user_id != owner_id:
        raise OmnigentError(
            "only the session owner may approve local machine actions",
            code=ErrorCode.FORBIDDEN,
        )
```

Notes, all load-bearing:

- The check must run **before** any Future resolution or tombstoning —
  a 403 must leave the approval parked so the owner can still answer.
- Match on `_local_action_elicitations.get(id) == session_id`, not just
  membership, so a cross-session id can't be replayed.
- `get_session_owner_id` returns the first LEVEL_OWNER grant; sessions
  always get one at create (`create_session` seeds `LEVEL_OWNER`).
- Do NOT gate ordinary harness elicitations — collaborators answering an
  MCP prompt is existing behavior; only ids in
  `_local_action_elicitations` get the owner gate.
- Verify how `user_id` reaches this handler: the route uses `require_user`
  (see `_auth_helpers.py`) — thread the resolved user through if the
  events route currently discards it.

## 3. Terminal-attach invariants (verify only, no new code)

`_authorize_terminal_attach` in `omnigent/server/routes/terminal_attach.py`
already enforces: read access for `read_only=true`, owner for interactive.
This step only adds the missing server-route tests (step-05 cases
`test_collaborator_can_read_only_attach`,
`test_collaborator_interactive_attach_denied`) and confirms the tunnel
proxy path applies the same authorizer **before** opening the runner WS.

## 4. Focused tests — extend the sessions-events unit suite

```python
async def test_collaborator_approval_of_local_action_is_403(
    app_as, seeded_local_session, pending_local_action
):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    approval_id = await pending_local_action(session_id, kind="run_shell")
    resp = await app_as("bob").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": approval_id, "approved": True}},
    )
    assert resp.status_code == 403


async def test_owner_approval_still_resolves_and_forwards(
    app_as, seeded_local_session, pending_local_action, fake_runner
):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    approval_id = await pending_local_action(session_id, kind="run_shell")
    resp = await app_as("alice").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": approval_id, "approved": True}},
    )
    assert resp.status_code == 200
    assert fake_runner.last_approval == (approval_id, True)


async def test_harness_elicitation_is_not_owner_gated(
    app_as, seeded_local_session, pending_harness_elicitation
):
    session_id = await seeded_local_session(owner="alice", editors=["bob"])
    elicitation_id = await pending_harness_elicitation(session_id)
    resp = await app_as("bob").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": elicitation_id, "approved": True}},
    )
    assert resp.status_code == 200  # unchanged collaborator behavior
```

Adjust the event `type`/shape to whatever the existing resolution handler
actually accepts (read the handler at ~L4020 first — the exact envelope is
already exercised by existing elicitation tests; mirror those fixtures).
