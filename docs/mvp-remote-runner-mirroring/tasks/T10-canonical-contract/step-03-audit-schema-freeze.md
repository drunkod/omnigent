# T10 Step 03 — Audit schema and secret-safety freeze

Blocker #3. Persistence and upsert mechanics exist, but `LocalActionData`
allows extra fields and `AuditRecord.command_summary` stores the first 400
characters of the raw command. Exact-key removal does not remove bearer
tokens, command arguments, or absolute paths embedded in summaries.

## 1. Replace open-ended persisted data with an allowlist

Define a typed history record containing bounded, non-sensitive fields only:

```python
class LocalActionHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    kind: Literal["read_file", "list_dir", "write_file", "run_shell"]
    status: Literal["approved", "denied", "blocked", "completed", "failed"]
    policy_mode: PolicyMode
    workspace_id: str
    path_summary: list[str] = Field(default_factory=list, max_length=32)
    command_category: str | None = Field(default=None, max_length=80)
    duration_s: float | None = None
    exit_code: int | None = None
    output_truncated: bool = False
```

Do not persist raw `command`, `content`, `diff_preview`, `stdout`, `stderr`,
environment values, auth headers, or arbitrary producer fields. Keep full
results only in the live approval response if the UI needs them.

## 2. Normalize values before persistence

```python
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(token|password|secret|api[_-]?key)=\S+"),
)


def safe_command_category(command: str) -> str:
    if command.lstrip().startswith(("git status", "git diff")):
        return "git_read"
    return command.split(maxsplit=1)[0][:40] if command else "unknown"


def redact_summary(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result[:120]
```

Prefer category-only storage. If a relative path is needed for history,
normalize it after successful workspace resolution and reject absolute paths,
`..`, and home-directory expansion. Persisted records must never contain a
machine-specific absolute path.

## 3. Preserve terminal-status upsert semantics

Keep the existing terminal-status filter and `action_id` upsert, but construct
the allowlisted entity explicitly:

```python
def _persist_local_action_item(store, session_id: str, event: dict[str, Any]) -> None:
    if event.get("status") not in TERMINAL_LOCAL_ACTION_STATUSES:
        return
    data = LocalActionHistoryData(
        action_id=str(event["action_id"]),
        kind=event["kind"], status=event["status"],
        policy_mode=event["policy_mode"], workspace_id=event["workspace_id"],
        path_summary=relative_paths_only(event.get("path_summary", [])),
        command_category=safe_command_category(event.get("command_summary", "")),
        duration_s=event.get("duration_s"),
        exit_code=event.get("exit_code"),
        output_truncated=bool(event.get("output_truncated", False)),
    )
    store.upsert_local_action(session_id, NewConversationItem(
        type="local_action", response_id=data.action_id, data=data,
    ))
```

## 4. Tests

```python
def test_persistence_drops_embedded_secrets(store, conversation):
    event = audit_event(
        "completed",
        command_summary="curl -H 'Authorization: Bearer super-secret' https://x",
        path_summary=["/Users/alice/.ssh/id_ed25519"],
        stdout="private output",
    )
    persist(event)
    dumped = json.dumps(store.list_items(conversation.id, type="local_action").data)
    assert "super-secret" not in dumped
    assert "/Users/alice" not in dumped
    assert "private output" not in dumped
```

Also add route-level retrieval coverage through `GET /v1/sessions/{id}/items`.
The log-capture test should assert no auth headers, tokens, full commands, or
absolute home paths in captured records.

## Done when

- The persisted model is allowlisted and bounded.
- Secret-bearing commands and absolute paths are absent from history and logs.
- `action_id` upsert, terminal-only persistence, and items API retrieval remain
  covered; P8 audit history is re-checked only after these tests pass.

