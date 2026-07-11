# Step 05 — Security integration test suite

Goal: `tests/server/integration/test_remote_local_runner_permissions.py`
covering the owner/collaborator boundary, denial propagation, binding
ownership, and audit hygiene. Lands last; every case maps to a step above.

## Current evidence

The acceptance cases are covered across the existing focused suites:

- Owner-only approval and cross-session tag survival: `tests/server/integration/test_sessions_elicitation_resolve_url.py`.
- Denial forwarding and audit payload redaction: `tests/server/test_local_action_approval_gate.py` and `tests/server/test_local_action_persistence.py`.
- Foreign-runner binding rejection: `tests/server/test_remote_local_runner_flag.py`.
- Collaborator read-only attach and interactive-attach denial: `tests/server/routes/test_terminal_attach.py`.
- Runner-side secret stripping: `tests/runner/test_identity.py` and `tests/runner/test_local_actions.py`.

The consolidated integration fixture suite described below remains deferred;
the focused tests exercise the same authorization and persistence contracts.

Build the fixtures on the existing integration harness (the same app
factory + authed-client pattern the other `tests/server/integration/*`
files use — mirror `test_runner_ownership.py`, which already fakes an
owner-scoped runner). Fixture sketch:

```python
"""Owner/collaborator boundaries for local-runner sessions (T08)."""

import json

import pytest

# Fixtures to implement on the existing harness:
#   app_as(user)                 → authed client for that user
#   seeded_local_session(...)    → session bound to a fake online runner
#                                  (workspace ws_abc123), grants seeded
#                                  via permission_store (owner / readers /
#                                  editors)
#   pending_local_action(...)    → runner posts an mcp_elicitation with
#                                  data.kind + data.policy_mode set,
#                                  returns the minted elicitation_id
#   fake_runner                  → records forwarded approvals + writes
#   run_local_action(...)        → full round trip incl. approval


async def test_collaborator_can_read_only_attach(app_as, seeded_local_session):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    bob = app_as("bob")
    async with bob.websocket_connect(
        f"/v1/sessions/{session_id}/resources/terminals/terminal_agent/attach"
        "?read_only=true"
    ) as ws:
        first = await ws.receive_bytes()
    assert first  # attach succeeded


async def test_collaborator_interactive_attach_denied(app_as, seeded_local_session):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    bob = app_as("bob")
    async with bob.websocket_connect(
        f"/v1/sessions/{session_id}/resources/terminals/terminal_agent/attach"
    ) as ws:
        closed = await ws.receive()
    assert closed["code"] in (4401, 4403)


async def test_only_owner_approves_local_action(
    app_as, seeded_local_session, pending_local_action
):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    approval_id = await pending_local_action(session_id, kind="run_shell")
    bob_resp = await app_as("bob").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": approval_id, "approved": True}},
    )
    assert bob_resp.status_code == 403
    alice_resp = await app_as("alice").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": approval_id, "approved": True}},
    )
    assert alice_resp.status_code == 200


async def test_denied_action_reaches_runner_as_denied(
    app_as, seeded_local_session, pending_local_action, fake_runner
):
    session_id = await seeded_local_session(owner="alice")
    approval_id = await pending_local_action(session_id, kind="write_file")
    await app_as("alice").post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": approval_id, "approved": False}},
    )
    assert fake_runner.last_approval == (approval_id, False)
    assert fake_runner.writes == []  # nothing executed


async def test_foreign_user_cannot_bind_runner(app_as, online_runner_owned_by):
    online_runner_owned_by("alice", runner_id="runner_a")
    resp = await app_as("bob").post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "runner_id": "runner_a",
        "workspace_id": "ws_abc123",
    })
    assert resp.json()["error"]["code"] in ("forbidden", "not_found")


async def test_audit_events_have_no_payloads(
    app_as, seeded_local_session, run_local_action
):
    session_id = await seeded_local_session(owner="alice")
    await run_local_action(session_id, kind="write_file", approve=True)
    items = (await app_as("alice").get(f"/v1/sessions/{session_id}/items")).json()
    audit = [i for i in items["data"] if i["type"] == "session.local_action"]
    assert audit, "audit trail missing"
    dumped = json.dumps(audit)
    for key in ("content", "diff_preview", "stdout", "token"):
        assert f'"{key}"' not in dumped


async def test_logs_leak_no_secrets(
    caplog, run_local_action, seeded_local_session, app_as
):
    session_id = await seeded_local_session(owner="alice")
    await run_local_action(session_id, kind="run_shell", command="echo hi", approve=True)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "X-Omnigent-Runner-Tunnel-Token" not in joined
    assert "/Users/" not in joined and "/home/" not in joined
```

Adaptation notes (do these first, they're where sketches usually break):

1. **Approval envelope** — read the resolution handler at
   `sessions.py` ~L4020 and mirror the exact event `type`/`data` shape the
   existing elicitation tests use; the sketch's `{"type": "approval"}` is
   a placeholder.
2. **Attach close codes** — confirm the actual denial codes in
   `_authorize_terminal_attach` (4401/4403 are the sketch's guess).
3. **`pending_local_action`** — don't fake at the store level; drive it
   through the real `mcp_elicitation` POST the runner uses
   (`_request_local_action_approval` shape: `data.kind`,
   `data.policy_mode`, `data.risk_flags`), so the step-02 tagging path is
   what's actually under test.
4. Run with the repo's project harness:
   `nix develop --command bash -lc 'uv run --frozen --extra dev python -m pytest tests/server/integration/test_remote_local_runner_permissions.py -q'`
