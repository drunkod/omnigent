# Step 06 — Durable `session.local_action` persistence

Closes P8's last box ("Add session history audit records"). Today the runner
publishes `session.local_action` via the SSE relay (sanitized at
`sessions.py` ~L10053) but nothing persists it: a page refresh loses the
audit trail. This step stores the sanitized event as a conversation item.

## 1. Schema decision (make it explicitly, in the PR description)

Two viable shapes; prefer **A** unless item types are closed:

- **A. New item type `local_action`** — first-class, queryable, no schema
  migration if items store `type` + JSON payload (they do: native harness
  events already persist through the same pipeline).
- **B. Label-tagged generic event item** — no new type, but consumers must
  filter by payload key; worse for the history UI.

## 2. Persist at the relay (same place the sanitizer runs)

The relay loop already special-cases the event type. Extend it:

```python
# sessions.py — runner SSE relay loop (~L10053)
if evt_type == "session.local_action":
    from omnigent.server.audit_sanitizer import sanitize_audit_event

    event = sanitize_audit_event(event)
    if conversation_store is not None:
        # Persist the terminal statuses only: one row per action
        # lifecycle, not one per transition. "requested" arrives
        # first and is updated in place on the final status.
        status = event.get("status")
        if status in ("completed", "failed", "denied", "blocked", "approved"):
            await asyncio.to_thread(
                _persist_local_action_item,
                conversation_store,
                session_id,
                event,
            )
session_stream.publish(session_id, event)
```

```python
def _persist_local_action_item(
    conversation_store: ConversationStore,
    session_id: str,
    event: dict[str, Any],
) -> None:
    """Store one audit item per action, upserted by ``action_id``.

    The runner emits requested → approved/denied/blocked →
    completed/failed for the same ``action_id``; the stored item always
    reflects the latest status so history shows the outcome, not the
    intermediate states.
    """

    conversation_store.upsert_item(
        conversation_id=session_id,
        item_type="local_action",
        external_id=str(event.get("action_id", "")),
        payload=event,
    )
```

Adaptation notes (verify before coding — these are the likely breaks):

- Follow whatever the native-harness event persistence actually calls —
  grep the relay loop for the existing persist helper and mirror its
  signature; `upsert_item` above is the sketch's guess. If the store has
  no upsert, insert on first terminal status only.
- Keep persistence **after** sanitization (the sanitizer returns a copy,
  so the published variant is identical).
- `asyncio.to_thread` — the store is sync SQLAlchemy; don't block the
  relay loop.

## 3. Surface in the items API

If `GET /v1/sessions/{id}/items` serializes items generically by type,
nothing to do. Otherwise add `local_action` to the allowed/serialized set.

## 4. Tests

```python
# tests/server/test_local_action_persistence.py
import pytest

from omnigent.server.audit_sanitizer import sanitize_audit_event


def _audit_event(status: str, **extra: object) -> dict[str, object]:
    return {
        "type": "session.local_action",
        "action_id": "act_1",
        "session_id": "conv_x",
        "runner_id": "runner_1",
        "workspace_id": "ws_1",
        "kind": "write_file",
        "requested_by": "agent",
        "policy_mode": "manual",
        "status": status,
        **extra,
    }


def test_terminal_status_is_persisted_and_sanitized(store, persist) -> None:
    persist("conv_x", _audit_event("completed", diff_preview="SECRET"))
    items = store.list_items("conv_x", item_type="local_action")
    assert len(items) == 1
    assert items[0].payload["status"] == "completed"
    assert "diff_preview" not in items[0].payload


def test_intermediate_status_is_not_persisted(store, persist) -> None:
    persist("conv_x", _audit_event("requested"))
    assert store.list_items("conv_x", item_type="local_action") == []


def test_same_action_id_upserts_not_duplicates(store, persist) -> None:
    persist("conv_x", _audit_event("approved"))
    persist("conv_x", _audit_event("completed"))
    items = store.list_items("conv_x", item_type="local_action")
    assert len(items) == 1
    assert items[0].payload["status"] == "completed"
```

Plus the step-05 integration case `test_audit_events_have_no_payloads`
(fetch `/v1/sessions/{id}/items` after an approved write, assert no
`content`/`diff_preview`/`stdout`/`token` keys) becomes fully runnable
once this lands.

## Done when

- A refreshed page shows the audit trail from history, payload-free.
- One item per `action_id`, final status wins.
- P8 "Add session history audit records" checked with this as evidence.
