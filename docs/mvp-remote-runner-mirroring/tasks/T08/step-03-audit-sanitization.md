# Step 03 — Server-side audit sanitization

Goal: persisted `session.local_action` events never contain file contents,
diffs, command output, or tokens — even if a runner (or future producer)
misbehaves. The runner half already exists:
`omnigent/runner/app.py::_publish_local_action_audit` publishes
`AuditRecord.to_event()`, and the record intentionally carries only
summaries. This step adds the server-side belt-and-braces guard where
session events are persisted.

## 1. Sanitizer — `omnigent/server/audit_sanitizer.py`

```python
"""Redaction guard for persisted local-action audit events.

The runner's ``AuditRecord.to_event()`` already omits payloads (contents,
diffs, output). This server-side pass is defense in depth: a stale or
malicious runner build must not be able to persist secrets into session
history. Matching is exact-key for MVP; a later hardening pass can add
case-insensitive / alias matching (``Token``, ``auth_token``) if producers
prove messy.
"""

from __future__ import annotations

_AUDIT_FORBIDDEN_KEYS = frozenset(
    {"content", "diff_preview", "stdout", "stderr", "token"}
)


def sanitize_audit_event(value: object) -> object:
    """Recursively drop payload-bearing keys from an audit event.

    :param value: Decoded event payload (dict/list/scalar).
    :returns: The same structure with forbidden keys removed at every
        nesting level. Scalars pass through unchanged.
    """

    if isinstance(value, dict):
        return {
            k: sanitize_audit_event(v)
            for k, v in value.items()
            if k not in _AUDIT_FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [sanitize_audit_event(v) for v in value]
    return value
```

## 2. Wire into the persist path

Find the single place the session-event relay persists incoming runner
events with the conversation items (the same pipeline that stores native
harness events — grep `session.local_action` producers land in). Apply the
guard only to that event type so harness payloads are untouched:

```python
if event.get("type") == "session.local_action":
    event = sanitize_audit_event(event)
```

Important: sanitize at **persist** time, not at publish/SSE time — the live
approval card legitimately shows `diff_preview` in transit (T05 contract);
only history storage must be payload-free. If the same object is both
published and persisted, `sanitize_audit_event` already returns a copy, so
sanitizing the persisted variant does not mutate the SSE one.

## 3. Tests — `tests/server/test_audit_sanitizer.py`

```python
from omnigent.server.audit_sanitizer import sanitize_audit_event


def test_drops_forbidden_keys_at_top_level() -> None:
    event = {"kind": "write_file", "diff_preview": "secret", "status": "approved"}
    assert sanitize_audit_event(event) == {"kind": "write_file", "status": "approved"}


def test_recurses_into_nested_dicts_and_lists() -> None:
    event = {
        "kind": "run_shell",
        "payload": {"stdout": "secret", "nested": [{"token": "x", "ok": 1}]},
    }
    cleaned = sanitize_audit_event(event)
    assert cleaned == {"kind": "run_shell", "payload": {"nested": [{"ok": 1}]}}


def test_scalars_and_unknown_keys_pass_through() -> None:
    event = {"kind": "read_file", "path_summary": ["src/a.py"], "duration_s": 0.2}
    assert sanitize_audit_event(event) == event
```

Plus one integration case (lands in step-05's suite):
`test_audit_events_have_no_payloads` fetches
`GET /v1/sessions/{id}/items` after an approved `write_file` and asserts
no `content` / `diff_preview` / `stdout` / `token` key anywhere in the
persisted `session.local_action` items.
