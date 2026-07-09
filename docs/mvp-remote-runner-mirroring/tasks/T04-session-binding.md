# T04 — Local-runner session creation and workspace binding

Implements plan `02-server-runner-work-plan.md` Tasks 2.2/3.1 and checklist P5.

Ground truth (verified against current code):

- `conversations` already has `runner_id`, `host_id`, `workspace` (absolute path string)
  columns, plus `labels`; the store exposes `set_runner_id` (NULL→id CAS),
  `replace_runner_id`, `clear_runner_id`, `list_conversations_by_runner_id`, and a
  bind helper that sets `runner_id`/`host_id`/`workspace` together.
- `POST /v1/sessions` (`omnigent/server/routes/sessions.py` ~L13951) validates
  `SessionCreateRequest`, creates the row, then **already notifies the bound runner**
  with `POST /v1/sessions` over the tunnel client (`_get_runner_client`).
- `RunnerRouter` (`omnigent/runner/routing.py`) enforces runner-online +
  harness-capability on dispatch with `ErrorCode.RUNNER_UNAVAILABLE` /
  `ErrorCode.RUNNER_CAPABILITY_MISMATCH`.
- `TunnelRegistry.runner_owner(runner_id)` gives the tunnel owner for ownership checks.

Decision for MVP: **reuse the existing `runner_id` column, but do not overload
`conversations.workspace` with a display label**. The workspace path shown to the user is
non-authoritative UI metadata; the authoritative binding is the runner-enforced
`workspace_id`, stored in labels. Prefer labels such as `omnigent.workspace_id`,
`omnigent.workspace_label`, and `omnigent.execution_mode`. No migration needed; promote a
first-class column later if query patterns demand it.

## 1. New error codes — `omnigent/errors.py`

```python
class ErrorCode(str, Enum):
    ...  # existing members unchanged, including:
    # RUNNER_UNAVAILABLE = "runner_unavailable"
    # RUNNER_CAPABILITY_MISMATCH = "runner_capability_mismatch"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    WORKSPACE_OUTSIDE_ALLOWED_ROOTS = "workspace_outside_allowed_roots"
    TERMINAL_TRANSPORT_UNSUPPORTED = "terminal_transport_unsupported"
    LOCAL_ACTION_REQUIRES_APPROVAL = "local_action_requires_approval"
    LOCAL_ACTION_BLOCKED_BY_POLICY = "local_action_blocked_by_policy"
```

Map `WORKSPACE_*` to HTTP 409/404 in the existing error-to-status mapping so the UI can
render specific recovery actions (plan `02` Task 6.2: tests must assert the **code**,
not just the status).

## 2. Request model — extend `SessionCreateRequest`

In the entities module that defines `SessionCreateRequest` (pydantic):

```python
class SessionCreateRequest(BaseModel):
    ...  # existing fields (agent_id, host_id, labels, ...)
    runner_id: str | None = None
    """Pin the session to an already-paired local runner."""
    workspace_id: str | None = None
    """Approved workspace root on that runner (see runner hello)."""

    @model_validator(mode="after")
    def _workspace_requires_runner(self) -> "SessionCreateRequest":
        if self.workspace_id is not None and self.runner_id is None:
            raise ValueError("workspace_id requires runner_id")
        return self
```

## 3. Server-side bind validation — `omnigent/server/routes/sessions.py`

Add one helper and call it from `create_session` (JSON branch) before the conversation
row is created:

```python
async def _validate_local_runner_binding(
    *,
    body: SessionCreateRequest,
    registry: TunnelRegistry,
    user_id: str | None,
    harness: str | None,
) -> None:
    """Validate a runner/workspace binding at session create.

    Fail-fast with structured codes so the UI can render recovery
    actions (reconnect runner / pick another workspace / pick another
    agent) instead of a generic 500.

    :raises OmnigentError:
        ``runner_unavailable`` — runner not connected;
        ``forbidden`` — caller does not own the runner;
        ``runner_capability_mismatch`` — harness not advertised;
        ``workspace_not_found`` — workspace_id not advertised.
    """
    if body.runner_id is None:
        return
    session = registry.get(body.runner_id)
    if session is None:
        raise OmnigentError(
            f"runner {body.runner_id!r} is offline; start it with "
            "`omnigent host --server <url>` and retry",
            code=ErrorCode.RUNNER_UNAVAILABLE,
        )
    # Ownership: same rule the tunnel listing uses (owner-scoped).
    if (
        user_id is not None
        and session.owner is not None
        and session.owner != user_id
    ):
        raise OmnigentError(
            "runner belongs to another user",
            code=ErrorCode.FORBIDDEN,
        )
    if harness is not None:
        canonical = canonicalize_harness(harness) or harness
        advertised = {
            canonicalize_harness(h) or h for h in session.hello.harnesses
        }
        if canonical not in advertised:
            raise OmnigentError(
                f"runner {body.runner_id!r} does not support harness {harness!r}",
                code=ErrorCode.RUNNER_CAPABILITY_MISMATCH,
            )
    if body.workspace_id is not None:
        advertised = {
            ws.get("workspace_id") for ws in session.hello.workspace_roots
        }
        if body.workspace_id not in advertised:
            raise OmnigentError(
                f"workspace {body.workspace_id!r} is not advertised by "
                f"runner {body.runner_id!r}",
                code=ErrorCode.WORKSPACE_NOT_FOUND,
            )
```

Optionally follow up with the runner's bounded validation endpoint (T02) for fresher
metadata — a 4xx from it also aborts create:

```python
    if body.workspace_id is not None:
        rc = runner_router._client_for_runner(body.runner_id)  # expose a public accessor
        resp = await rc.post(f"/v1/runner/workspaces/{body.workspace_id}/validate")
        if resp.status_code >= 400:
            raise OmnigentError(
                f"workspace validation failed: {resp.text[:200]}",
                code=ErrorCode.WORKSPACE_NOT_FOUND,
            )
```

## 4. Persist the binding

Where `create_session` creates the conversation row (the store's `create_conversation`
already accepts `runner_id=` and `workspace=`):

```python
        workspace_label: str | None = None
        if body.workspace_id is not None:
            # Display/UX only; enforcement stays on the runner (T02).
            workspace_label = _advertised_path_label(session.hello, body.workspace_id)

        conv = conversation_store.create_conversation(
            ...,
            runner_id=body.runner_id,
            # Keep the existing workspace column reserved for real runtime paths;
            # do not write display-only labels into it. Omit the argument or
            # preserve existing behavior unless the current store requires an
            # explicit value.
            labels={
                **(body.labels or {}),
                **(
                    {
                        "omnigent.execution_mode": "local_runner",
                        **(
                            {
                                "omnigent.workspace_id": body.workspace_id,
                                "omnigent.workspace_label": workspace_label,
                            }
                            if body.workspace_id
                            else {}
                        ),
                    }
                    if body.runner_id
                    else {}
                ),
            },
        )
```

Make this explicit in the implementation notes: `omnigent.workspace_label` is for display
only and must never be used for path resolution, authorization, or workspace containment.
Only the runner-side workspace registry (T02) is authoritative.

The **existing** post-create runner notification (`_rc.post("/v1/sessions", json={...})`)
must carry the binding so the runner can resolve the cwd (T02 §3):

```python
                await _rc.post(
                    "/v1/sessions",
                    json={
                        "session_id": resp.id,
                        "agent_id": conv.agent_id,
                        # ── new ──
                        "workspace_id": conv.labels.get("omnigent.workspace_id"),
                        "execution_mode": conv.labels.get("omnigent.execution_mode"),
                    },
                )
```

Session snapshot: `_build_session_response` already returns `runner_id` and
`workspace`; add the two labels to the response (they're already in `labels`, so the UI
can read them — just document the label keys as API contract in
`designs/REMOTE_LOCAL_RUNNER.md`).

## 5. Fork/resume semantics (explicit rule)

- **Fork**: copy `runner_id` (existing behavior for native sub-agents) **and** the
  `omnigent.workspace_id` label. Same workspace, same runner — a fork is a
  continuation of work on the same checkout.
- **Resume with runner offline**: keep the binding; return
  `runner_unavailable` on dispatch (already `RunnerRouter` behavior). Never silently
  rebind a local-runner session to a different runner.
- **Switch-agent**: re-run `_validate_local_runner_binding` with the new harness;
  reject with `runner_capability_mismatch` if unsupported.

## 6. Integration tests — `tests/server/integration/test_remote_local_runner_sessions.py`

```python
"""Session create bound to a local runner + workspace."""

import pytest

from omnigent.runner.transports.ws_tunnel.frames import HelloFrame

WS = {
    "workspace_id": "ws_abc123",
    "display_name": "demo",
    "path_label": "~/projects/demo",
    "capabilities": ["read", "write", "shell", "git", "terminal"],
}


def _register_fake_runner(registry, runner_id="runner_test1", owner=None, **hello_kw):
    hello = HelloFrame(
        runner_version="0.9.0",
        frame_protocol_version=1,
        harnesses=hello_kw.pop("harnesses", ["codex"]),
        envs=["posix"],
        mode="local",
        workspace_roots=hello_kw.pop("workspace_roots", [WS]),
        terminal_transports=hello_kw.pop("terminal_transports", ["pty"]),
    )
    # FakeWS pattern already used by tests/runner/test_ws_tunnel_* —
    # reuse that fixture here.
    return registry.register(runner_id, FakeWS(), hello, owner=owner)


async def test_create_binds_runner_and_workspace(app_client, tunnel_registry):
    _register_fake_runner(tunnel_registry)
    resp = await app_client.post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "runner_id": "runner_test1",
        "workspace_id": "ws_abc123",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["runner_id"] == "runner_test1"
    assert body["labels"]["omnigent.workspace_id"] == "ws_abc123"
    assert body["labels"]["omnigent.execution_mode"] == "local_runner"


async def test_create_offline_runner_is_structured_error(app_client):
    resp = await app_client.post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "runner_id": "runner_gone",
        "workspace_id": "ws_abc123",
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "runner_unavailable"


async def test_create_unknown_workspace_rejected(app_client, tunnel_registry):
    _register_fake_runner(tunnel_registry)
    resp = await app_client.post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "runner_id": "runner_test1",
        "workspace_id": "ws_other",
    })
    assert resp.json()["error"]["code"] == "workspace_not_found"


async def test_create_foreign_runner_forbidden(app_client_as_bob, tunnel_registry):
    _register_fake_runner(tunnel_registry, owner="alice@example.com")
    resp = await app_client_as_bob.post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "runner_id": "runner_test1",
        "workspace_id": "ws_abc123",
    })
    assert resp.status_code in (403, 404)
    assert resp.json()["error"]["code"] in ("forbidden", "not_found")


async def test_capability_mismatch(app_client, tunnel_registry):
    _register_fake_runner(tunnel_registry, harnesses=["claude-code"])
    resp = await app_client.post("/v1/sessions", json={
        "agent_id": "agent_codex",   # resolves to harness "codex"
        "runner_id": "runner_test1",
        "workspace_id": "ws_abc123",
    })
    assert resp.json()["error"]["code"] == "runner_capability_mismatch"


async def test_workspace_without_runner_is_422(app_client):
    resp = await app_client.post("/v1/sessions", json={
        "agent_id": "agent_codex",
        "workspace_id": "ws_abc123",
    })
    assert resp.status_code == 422
```

## Acceptance checklist

- [ ] `SessionCreateRequest` accepts `runner_id` + `workspace_id`; workspace requires runner.
- [ ] Bind validation: online, owner, harness capability, advertised workspace — each with
      its structured error code.
- [ ] Binding persisted via existing `runner_id` plus labels such as
      `omnigent.workspace_id` / `omnigent.workspace_label` /
      `omnigent.execution_mode`; display labels never replace canonical runtime paths.
- [ ] Runner notification payload carries `workspace_id`; runner resolves cwd from it (T02 §3).
- [ ] Fork copies binding; resume never silently rebinds; switch-agent revalidates capability.
- [ ] Integration tests assert error **codes**, not just statuses.
