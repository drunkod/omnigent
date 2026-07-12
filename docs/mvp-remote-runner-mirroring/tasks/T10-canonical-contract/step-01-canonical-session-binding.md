# T10 Step 01 — Canonical `runner_id + workspace_id` session contract

Blocker #1. The binding helpers are done and tested; this step gives them
their first production callers and makes the public API match the plan:
the server accepts opaque identifiers and persists identifiers/labels only
— never raw local paths — for local-runner sessions.

## 1. Extend `SessionCreateRequest` (schemas.py ~L1311)

```python
class SessionCreateRequest(BaseModel):
    ...
    labels: dict[str, str] = Field(default_factory=dict)
    local_runner_policy: str | None = None
    # Canonical local-runner binding (T04/T10). Mutually exclusive with
    # host_id + workspace: a request may bind EITHER to a paired local
    # runner by opaque ids OR use the host-launch flow, not both.
    runner_id: str | None = None
    workspace_id: str | None = None

    @model_validator(mode="after")
    def _validate_binding_exclusivity(self) -> "SessionCreateRequest":
        if self.runner_id is not None and self.host_id is not None:
            raise ValueError("runner_id and host_id are mutually exclusive")
        if self.workspace_id is not None and self.runner_id is None:
            raise ValueError("workspace_id requires runner_id")
        if self.runner_id is not None and self.workspace is not None:
            raise ValueError(
                "local-runner sessions bind workspaces by workspace_id; "
                "raw workspace paths are host-launch only"
            )
        return self
```

## 2. Wire the existing validator into `_create_session_from_existing_agent`

Insert after the harness override validation (~L12260), before any row is
created. The helpers are already written — this is call-site plumbing:

```python
# sessions.py — local-runner binding (T10). validate_local_runner_binding
# checks: runner online, caller owns it, workspace_id advertised in the
# runner's hello, harness supported. Fail-loud before create_conversation.
if body.runner_id is not None:
    from omnigent.server.session_binding import (
        merge_local_runner_labels,
        validate_local_runner_binding,
    )

    binding = validate_local_runner_binding(
        registry=runner_router,          # adapt: LocalRunnerRegistryLike
        runner_id=body.runner_id,
        workspace_id=body.workspace_id,
        harness=resolved_harness,        # from _validated_harness_override
        user_id=user_id,
    )
    initial_labels = merge_local_runner_labels(
        initial_labels,
        runner_id=body.runner_id,
        workspace_id=body.workspace_id,
        workspace_label=binding.workspace_label,
        policy_mode=body.local_runner_policy,
    )
```

Adaptation notes:

- Match the helpers' real signatures in `session_binding.py` — the sketch
  compresses them. `merge_local_runner_labels` already sets
  `omnigent.execution_mode = "local_runner"`, `omnigent.workspace_id`,
  `omnigent.workspace_label`, and (since `540eb918`) the policy label.
- Persist `runner_id` on the conversation row the same way host-launch
  does (`create_conversation(..., runner_id=...)`) so terminal attach and
  reconnect routing work unchanged.
- The `remote_local_runner` flag check (~L14057) must now also gate
  `body.runner_id is not None`, not just `local_runner_policy`:

```python
if (body.local_runner_policy is not None or body.runner_id is not None) \
        and not remote_local_runner_enabled():
    raise OmnigentError(..., code=ErrorCode.INVALID_INPUT)
```

## 3. Snapshot, fork, resume

- **Snapshot**: labels already flow to the UI (`bd527fa4` reads
  `omnigent.workspace_label` / `omnigent.local_runner_policy` in the
  header) — verify `omnigent.workspace_id` is included, not stripped.
- **Fork/child**: `inherited_runner_id` (~L12263) already copies the
  parent's runner with an ownership re-check. Extend it to also copy the
  workspace labels so a child lands in the same workspace:

```python
if inherited_runner_id is not None and parent_conv is not None:
    parent_labels = parent_conv.labels or {}
    for key in (WORKSPACE_ID_LABEL_KEY, WORKSPACE_LABEL_LABEL_KEY,
                EXECUTION_MODE_LABEL_KEY):
        if key in parent_labels:
            initial_labels.setdefault(key, parent_labels[key])
```

- **Resume**: no new work if resume reuses the conversation row (labels
  persist); add the assertion to the tests below.

## 4. Runner receives the workspace

Trace how host-launch passes `workspace` to the runner today and send the
**workspace_id** for local-runner sessions instead; the runner resolves it
via its `WorkspaceRegistry` (`resolve_in_workspace` is already
id-keyed). The server must never send a path it computed itself.

## 5. Route-level tests — `tests/server/integration/test_remote_local_runner_sessions.py`

This is the file the P5 checklist row has always pointed at. Cases:

```python
"""Canonical runner_id + workspace_id session binding (T10)."""


async def test_create_with_runner_and_workspace_persists_labels(
    auth_client, online_runner_owned_by
):
    online_runner_owned_by(
        "alice@example.com", runner_id="runner_a",
        workspaces=[{"workspace_id": "ws_1", "path_label": "~/proj"}],
        harnesses=["codex"],
    )
    resp = await auth_client.post(
        "/v1/sessions",
        json={"agent_id": AGENT, "runner_id": "runner_a", "workspace_id": "ws_1"},
        headers=_as("alice@example.com"),
    )
    assert resp.status_code == 201
    labels = resp.json()["labels"]
    assert labels["omnigent.execution_mode"] == "local_runner"
    assert labels["omnigent.workspace_id"] == "ws_1"
    assert labels["omnigent.workspace_label"] == "~/proj"


async def test_foreign_runner_is_rejected(auth_client, online_runner_owned_by):
    online_runner_owned_by("alice@example.com", runner_id="runner_a")
    resp = await auth_client.post(
        "/v1/sessions",
        json={"agent_id": AGENT, "runner_id": "runner_a", "workspace_id": "ws_1"},
        headers=_as("bob@example.com"),
    )
    assert resp.status_code in (403, 404)


async def test_unadvertised_workspace_is_rejected(...):
    # runner online, owned, but workspace_id not in its hello → 400/404


async def test_unsupported_harness_is_rejected(...):
    # runner advertises harnesses=["claude"], agent resolves to codex → 400


async def test_raw_workspace_path_rejected_for_runner_sessions(...):
    # runner_id + workspace → 422 from the model validator


async def test_child_inherits_workspace_binding(...):
    # parent bound to runner_a/ws_1 → child created with
    # parent_session_id carries the same three labels
```

## 6. Frontend follow-through (小 slice, after server lands)

`web/src/lib/remoteRunner.ts`'s `RemoteHost` has no workspace collection —
extend it and switch the T09 picker's create payload from
`host_id + workspace path` to `runner_id + workspace_id` for paired
runners. Keep the host-launch path untouched for its existing flow.

## Done when

- All six route tests green; P5's three reopened rows re-checked with this
  file as evidence.
- `validate_local_runner_binding` and `merge_local_runner_labels` each
  have ≥1 production caller (grep proves it).
- No code path accepts a raw path for a `runner_id`-bound session.
