# Step 04 — Feature flag and telemetry

Two small, independent slices; both are prerequisites for the rollout gates
in the T08 plan (§6).

## 1. Feature flag — `remote_local_runner`

Off by default; surfaced in `/v1/info` capabilities so the web UI can hide
the runner picker (Deferred B reads this).

```python
# settings module (follow the existing env-var pattern)
remote_local_runner_enabled: bool = _env_bool("OMNIGENT_REMOTE_LOCAL_RUNNER", False)
```

```python
# /v1/info payload addition
"capabilities": {
    ...,
    "remote_local_runner": settings.remote_local_runner_enabled,
}
```

Enforce at session create, not just in the UI:

```python
# create_session — before binding validation
if body.get("runner_id") and not settings.remote_local_runner_enabled:
    raise OmnigentError(
        "remote local runner support is not enabled on this server",
        code=ErrorCode.INVALID_REQUEST,
    )
```

Test:

```python
async def test_runner_binding_rejected_when_flag_off(app_as, online_runner_owned_by):
    online_runner_owned_by("alice", runner_id="runner_a")
    resp = await app_as("alice").post("/v1/sessions", json={
        "agent_id": "agent_codex", "runner_id": "runner_a", "workspace_id": "ws_abc123",
    })
    assert resp.status_code == 400


async def test_info_advertises_flag(app_as, enable_remote_local_runner):
    info = (await app_as("alice").get("/v1/info")).json()
    assert info["capabilities"]["remote_local_runner"] is True
```

## 2. Telemetry counters (checklist P11)

Follow the existing patterns in `omnigent/runtime/telemetry.py` and
`omnigent/server/performance_metrics.py`. Metric set from the plan:

```python
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

Emission points (all already exist as code paths):

- tunnel connect/disconnect: the runner tunnel route registration and
  deregistration in the tunnel registry.
- attach + close codes: `terminal_attach.py` where close codes are chosen.
- local actions: `LocalActionGateway._gate` outcomes (`approved` /
  `denied` / `blocked`) — one counter bump per `_publish_audit` status
  transition keeps the metric consistent with the audit trail.
- approval decisions: the step-02 resolution handler.

Log hygiene rule (enforced by the step-05 log-capture test): no file
contents, no full command output, no pairing tokens, no auth headers, no
absolute home paths. When logging paths, log `record.path_summary`
(workspace-relative), never resolved absolute paths.
