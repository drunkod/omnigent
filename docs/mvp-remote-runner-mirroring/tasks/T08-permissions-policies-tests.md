# T08 — Policy presets, permission enforcement, and the security test suite

Implements plan `04-permissions-security-tests.md` and checklist P8 + P10 (permission
portion).

Ground truth (verified against current code):

- `omnigent/server/routes/terminal_attach.py` (`_authorize_terminal_attach`) already
  enforces read-access for read-only attach and owner-access for interactive attach.
- `omnigent/stores/permission_store/*` provides session grants (`LEVEL_OWNER` used in
  `create_session`); `omnigent/server/routes/_auth_helpers.py` has `require_user`.
- Policy engine lives in `omnigent/policies/*` with builtins in
  `omnigent/policies/builtins/*`; native ask-gates flow through
  `omnigent/runner/pending_approvals.py` and
  `sessions.py::_forward_approval_to_runner`.
- Risk classification itself is runner-side (`workspace_policy.py`, T05). Policies
  here choose the **mode** and record decisions in session history.

## 1. Built-in policy presets — `omnigent/policies/builtins/local_runner.py`

```python
"""Built-in policy presets for remote-local runner sessions.

The preset resolves to a PolicyMode (T05) that the server passes to
the runner gateway with every local action. The runner re-checks
classification independently (defense in depth): a compromised or
stale server cannot grant more than the runner's own blocklist allows.
"""

from __future__ import annotations

from omnigent.runner.workspace_policy import PolicyMode

# Preset id → (PolicyMode, human description). Ids are API contract.
LOCAL_RUNNER_PRESETS: dict[str, tuple[PolicyMode, str]] = {
    "local_runner_manual": (
        PolicyMode.MANUAL,
        "Ask before every file write and shell command. Reads inside the "
        "workspace are allowed. Recommended default.",
    ),
    "local_runner_assisted": (
        PolicyMode.ASSISTED,
        "Reads, listing, search, git status/diff are allowed. Writes, "
        "patches, and shell commands ask first.",
    ),
    "local_runner_auto": (
        PolicyMode.AUTO,
        "Writes and shell inside the workspace are allowed. Package "
        "installs, destructive git, file removal, and anything risky "
        "still asks. Workspace escapes are always blocked.",
    ),
}

DEFAULT_LOCAL_RUNNER_PRESET = "local_runner_manual"


def policy_mode_for_session(labels: dict[str, str]) -> PolicyMode:
    """Resolve the effective mode from session labels.

    :param labels: Conversation labels; reads
        ``omnigent.local_runner_policy`` (preset id).
    :returns: The preset's mode; unknown/absent ids fall back to MANUAL
        (fail closed).
    """
    preset = labels.get("omnigent.local_runner_policy", DEFAULT_LOCAL_RUNNER_PRESET)
    mode_desc = LOCAL_RUNNER_PRESETS.get(preset)
    if mode_desc is None:
        return PolicyMode.MANUAL
    return mode_desc[0]
```

Register the presets wherever builtins are seeded (follow the existing pattern in
`omnigent/policies/builtins/__init__.py`) so they appear in the policies API/UI, and
document that changing the preset only affects **future** actions.

## 2. Owner-only approvals for local actions

MVP decision (plan 04 "Session permissions"): only the session **owner** may approve
or deny a local action; collaborators may watch. Enforce at the approval-resolution
route (the one `_forward_approval_to_runner` serves), not in the UI:

```python
# sessions.py — inside the approval-resolution handler for local actions
grants = await asyncio.to_thread(permission_store.grants_for_session, session_id)
owner = _owner_from_grants(grants)          # existing helper
if user_id is None or user_id != owner:
    raise OmnigentError(
        "only the session owner may approve local machine actions",
        code=ErrorCode.FORBIDDEN,
    )
```

Also confirm (with tests, §5) the two attach invariants already implemented:
read-only attach needs read access; interactive attach needs owner. The tunnel proxy
path must apply the **same** `_authorize_terminal_attach` before opening a WS channel
to the runner — verify this ordering, since the check must happen server-side, never
runner-side.

## 3. Audit records into session history

Every gateway audit record (T05 `AuditRecord.to_event()`) is published as a
`session.local_action` session event and persisted with the conversation items so the
history shows the full trail: requested → approved/denied/blocked → completed/failed.

```python
# runner app: publish_audit wiring
def _publish_audit(record: AuditRecord) -> None:
    _publish_session_event(record.session_id, "session.local_action", record.to_event())
    # Persisted server-side by the existing session-event relay, same
    # pipeline that stores native harness events.
```

Server-side redaction guard (belt and braces — the runner already sends relative
paths only):

```python
_AUDIT_FORBIDDEN_KEYS = ("content", "diff_preview", "stdout", "stderr", "token")

def _sanitize_audit_event(event: dict[str, object]) -> dict[str, object]:
    """Drop payload-bearing keys before persisting server-side."""
    return {k: v for k, v in event.items() if k not in _AUDIT_FORBIDDEN_KEYS}
```

## 4. Telemetry (checklist P11, plan 04 metrics)

Counters/gauges via the existing `omnigent/runtime/telemetry.py` +
`omnigent/server/performance_metrics.py` patterns:

```python
# metric name → labels
"omnigent.runner.tunnel.connect_total"        # {mode}
"omnigent.runner.tunnel.disconnect_total"     # {mode, reason}
"omnigent.runner.tunnel.reconnect_latency_s"  # histogram
"omnigent.runner.capability_mismatch_total"   # {harness}
"omnigent.workspace.validation_failed_total"  # {code}
"omnigent.terminal.attach_total"              # {transport, read_only}
"omnigent.terminal.attach_close_total"        # {close_code}
"omnigent.local_action.total"                 # {kind, status, policy_mode}
"omnigent.local_action.blocked_total"         # {risk_flag}
"omnigent.approval.decision_total"            # {decision}
```

Log hygiene rules (enforced by the §5 log-capture test): no file contents, no full
command output, no pairing tokens, no auth headers, no absolute local home paths.

## 5. Permission integration tests — `tests/server/integration/test_remote_local_runner_permissions.py`

```python
"""Owner/collaborator boundaries for local-runner sessions."""

import pytest

# Fixtures assumed from existing integration harness:
#   app_as(user) → authed client; seeded_local_session(owner=...) →
#   session bound to a fake online runner with workspace ws_abc123.


async def test_collaborator_can_read_only_attach(app_as, seeded_local_session):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    bob = app_as("bob")
    async with bob.websocket_connect(
        f"/v1/sessions/{session_id}/resources/terminals/terminal_agent/attach"
        "?read_only=true"
    ) as ws:
        first = await ws.receive_bytes()          # seeded capture-pane output
    assert first  # attach succeeded


async def test_collaborator_interactive_attach_denied(app_as, seeded_local_session):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    bob = app_as("bob")
    async with bob.websocket_connect(
        f"/v1/sessions/{session_id}/resources/terminals/terminal_agent/attach"
    ) as ws:
        closed = await ws.receive()
    assert closed["code"] in (4401, 4403)         # existing denial close codes


async def test_only_owner_approves_local_action(app_as, seeded_local_session, pending_local_action):
    session_id = await seeded_local_session(owner="alice", readers=["bob"])
    approval_id = await pending_local_action(session_id, kind="run_shell")
    bob_resp = await app_as("bob").post(
        f"/v1/sessions/{session_id}/approvals/{approval_id}", json={"approved": True}
    )
    assert bob_resp.status_code == 403
    alice_resp = await app_as("alice").post(
        f"/v1/sessions/{session_id}/approvals/{approval_id}", json={"approved": True}
    )
    assert alice_resp.status_code == 200


async def test_denied_action_reaches_runner_as_denied(app_as, seeded_local_session,
                                                      pending_local_action, fake_runner):
    session_id = await seeded_local_session(owner="alice")
    approval_id = await pending_local_action(session_id, kind="write_file")
    await app_as("alice").post(
        f"/v1/sessions/{session_id}/approvals/{approval_id}", json={"approved": False}
    )
    assert fake_runner.last_approval == (approval_id, False)
    assert fake_runner.writes == []               # nothing executed


async def test_foreign_user_cannot_bind_runner(app_as, online_runner_owned_by):
    online_runner_owned_by("alice", runner_id="runner_a")
    resp = await app_as("bob").post("/v1/sessions", json={
        "agent_id": "agent_codex", "runner_id": "runner_a", "workspace_id": "ws_abc123",
    })
    assert resp.json()["error"]["code"] in ("forbidden", "not_found")


async def test_audit_events_have_no_payloads(app_as, seeded_local_session, run_local_action):
    session_id = await seeded_local_session(owner="alice")
    await run_local_action(session_id, kind="write_file", approve=True)
    items = (await app_as("alice").get(f"/v1/sessions/{session_id}/items")).json()
    audit = [i for i in items["data"] if i["type"] == "session.local_action"]
    assert audit, "audit trail missing"
    for event in audit:
        for key in ("content", "diff_preview", "stdout", "token"):
            assert key not in event


async def test_logs_leak_no_secrets(caplog, run_local_action, seeded_local_session, app_as):
    session_id = await seeded_local_session(owner="alice")
    await run_local_action(session_id, kind="run_shell", command="echo hi", approve=True)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "X-Omnigent-Runner-Tunnel-Token" not in joined
    assert "/Users/" not in joined and "/home/" not in joined
```

## 6. Rollout gates (unchanged from plan 04, wired to CI)

- **Gate 1 (dev)**: feature flag `remote_local_runner` off by default (surface in
  `/v1/info` capabilities, T01/T04); manual mode only; codex-native e2e green; unit
  suites T01/T02/T05 green.
- **Gate 2 (alpha)**: second harness; picker + approval + diff UI (T07); tunnel,
  permission, and escape-blocking integration suites green.
- **Gate 3 (beta)**: assisted mode; pairing docs (`docs/remote-local-runner.md`);
  e2e UI coverage; version-skew compatibility tests (T01) green in both directions.

Feature flag sketch:

```python
# /v1/info payload addition
"capabilities": {
    ...,
    "remote_local_runner": settings.remote_local_runner_enabled,  # env: OMNIGENT_REMOTE_LOCAL_RUNNER=1
}
```

UI hides the runner picker when the capability is false.

## Acceptance checklist

- [ ] Three presets registered; label-driven; unknown preset falls back to MANUAL.
- [ ] Approvals owner-only, enforced server-side at the resolution route.
- [ ] Attach permission invariants covered by tunnel-path tests.
- [ ] Audit trail persisted, payload-free; log-capture test proves no secret/path leaks.
- [ ] Telemetry counters emitted with the listed names/labels.
- [ ] Feature flag gates the whole surface; rollout gates mapped to CI suites.
