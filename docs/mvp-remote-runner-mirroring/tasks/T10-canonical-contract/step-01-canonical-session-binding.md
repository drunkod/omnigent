# T10 Step 01 — Canonical runner discovery and session binding

Blocker #1. The server needs one owner-scoped discovery contract and one local-runner
create contract based on opaque IDs. The existing host-launch contract remains valid
for host-managed launches but must not be reused by the local-runner picker.

## Contract decision

### Existing host-launch mode

```json
{
  "host_id": "host_...",
  "workspace": "/absolute/path/on/host"
}
```

This path asks a host daemon to launch a runner in a server-selected absolute path. It
is not the local-runner mirroring contract and remains separate.

### Canonical local-runner mode

```json
{
  "runner_id": "runner_...",
  "workspace_id": "ws_...",
  "local_runner_policy": "manual"
}
```

The server validates live advertised metadata and persists identifiers/display labels
only. It never receives, reconstructs, or forwards a local absolute workspace path for
this mode.

## 1. Owner-scoped discovery API

Add a stable server projection for the UI. Recommended endpoint:

```text
GET /v1/runners
```

An enriched `/v1/hosts` response is acceptable only if it preserves the exact
semantics below and exposes an explicit `runner_id`; do not force the UI to treat
`host_id` as a runner identifier.

```json
{
  "data": [
    {
      "runner_id": "runner_abc",
      "host_id": "host_optional",
      "display_name": "Workstation",
      "online": true,
      "runner_version": "0.3.0",
      "os": "darwin",
      "arch": "arm64",
      "harnesses": ["codex", "claude-native"],
      "terminal_transports": ["control", "pty"],
      "tool_capabilities": ["read_file", "write_file", "run_shell"],
      "workspaces": [
        {
          "workspace_id": "ws_123",
          "display_name": "omnigent",
          "path_label": "~/src/omnigent",
          "capabilities": ["read", "write", "shell", "git", "terminal"]
        }
      ]
    }
  ]
}
```

Requirements:

- scope results to the authenticated owner;
- derive fields from live tunnel hello metadata and persisted ownership;
- include offline entries only when ownership and reconnect semantics are explicit;
- omit root paths, tokens, auth headers, and other machine secrets;
- validate/normalize the response with a server schema;
- add tests for owner isolation, malformed hello entries, offline state, and no-path
  exposure.

## 2. Extend `SessionCreateRequest`

```python
class SessionCreateRequest(BaseModel):
    ...
    local_runner_policy: str | None = None
    runner_id: str | None = None
    workspace_id: str | None = None

    @model_validator(mode="after")
    def _validate_local_runner_binding_shape(self) -> "SessionCreateRequest":
        if self.runner_id is not None and self.host_id is not None:
            raise ValueError("runner_id and host_id are mutually exclusive")
        if self.workspace_id is not None and self.runner_id is None:
            raise ValueError("workspace_id requires runner_id")
        if self.runner_id is not None and self.workspace_id is None:
            raise ValueError("runner_id requires workspace_id")
        if self.runner_id is not None and self.workspace is not None:
            raise ValueError(
                "local-runner sessions bind by workspace_id; raw workspace paths "
                "are not accepted"
            )
        return self
```

The multipart/session-upload create path must either support the same binding metadata
or reject local-runner fields explicitly; do not leave two create routes with different
security behavior.

## 3. Route wiring

Before creating a conversation row:

1. resolve the selected agent's effective harness;
2. require the feature flag;
3. validate the runner is online and owned by the caller;
4. validate the workspace ID is advertised by that runner;
5. validate the runner advertises the harness;
6. derive a display-only workspace label from the advertised entry;
7. persist the runner and labels atomically with conversation creation.

Use the existing helpers in `omnigent/server/session_binding.py`, adapting their real
signatures rather than duplicating checks.

```python
binding = validate_local_runner_binding(
    registry=tunnel_registry,
    runner_id=body.runner_id,
    workspace_id=body.workspace_id,
    user_id=user_id,
    harness=resolved_harness,
)

labels = merge_local_runner_labels(
    initial_labels,
    runner_id=body.runner_id,
    workspace_id=body.workspace_id,
    workspace_label=advertised_workspace_label(binding.hello, body.workspace_id),
)
labels[LOCAL_RUNNER_POLICY_LABEL_KEY] = normalized_policy

conversation_store.create_conversation(
    ...,
    runner_id=body.runner_id,
    labels=labels,
)
```

The sketch compresses the actual store and helper signatures. Preserve the existing
host-launch transaction/error cleanup behavior.

## 4. Runner initialization

When assigning or reconnecting the session, send `workspace_id` and execution mode to
the runner. The runner resolves the workspace through its local `WorkspaceRegistry`.
The server must not convert `workspace_id` to a path.

The runner must fail loudly if:

- the workspace was revoked after session creation;
- the workspace no longer exists;
- the runner restarted without that workspace approval; or
- the session's binding does not match the runner receiving it.

Define whether a revoked/missing workspace blocks the next action only or marks the
whole session degraded. Surface the selected behavior in the snapshot and T09 copy.

## 5. Snapshot and inheritance

Snapshot fields/labels must expose:

- `runner_id` or an opaque runner reference suitable for diagnostics;
- `omnigent.execution_mode = local_runner`;
- `omnigent.workspace_id`;
- `omnigent.workspace_label`;
- `omnigent.local_runner_policy`;
- current runner/workspace availability when the snapshot already carries liveness.

Child/fork behavior:

- inherit runner/workspace/policy only when the operation is defined as same-machine;
- revalidate caller access and current advertisement before creating the child;
- never inherit the display label without the opaque ID;
- reject a conflicting explicit child binding.

Resume/reconnect behavior:

- reuse the persisted binding;
- revalidate it against the live runner on the next initialization/action;
- do not replace it from client-local state.

## 6. Tests

Discovery tests:

- owner sees owned runner; another user does not;
- response includes explicit `runner_id` and opaque workspace IDs;
- response contains no absolute root or token;
- malformed capability entries are ignored or fail with the documented behavior;
- offline state is represented consistently.

Create-route tests:

- valid owner/runner/workspace/harness creates and persists labels;
- foreign runner is rejected;
- unknown/unadvertised workspace is rejected;
- unsupported harness is rejected;
- feature-off request is rejected;
- `runner_id + host_id` is rejected;
- `runner_id + workspace` is rejected;
- `runner_id` without `workspace_id` is rejected;
- multipart create follows the same rule;
- child/fork inheritance revalidates and preserves the binding;
- resume/reconnect sends `workspace_id`, not a path;
- revoked workspace fails loudly.

## Frontend handoff

T09 consumes the exact discovery schema and sends:

```json
{
  "runner_id": "runner_abc",
  "workspace_id": "ws_123",
  "local_runner_policy": "manual"
}
```

No probing or `workspacePathFor(...)` fallback remains after this step.

## Done when

- discovery and create models are documented and validated;
- `validate_local_runner_binding` and label helpers have production callers;
- local-runner mode never accepts or emits a raw local root;
- snapshot/inheritance/reconnect tests are green; and
- T09 can implement from generated/typed API evidence without guessing field names.
