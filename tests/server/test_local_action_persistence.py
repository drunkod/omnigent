from __future__ import annotations

from omnigent.server.audit_sanitizer import sanitize_audit_event
from omnigent.server.routes.sessions import _persist_local_action_item
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore


def _event(status: str, **extra: object) -> dict[str, object]:
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


def test_terminal_local_action_is_sanitized_and_persisted(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(
        store,
        conversation.id,
        sanitize_audit_event(_event("completed", diff_preview="SECRET")),
    )

    items = store.list_items(conversation.id, type="local_action")
    assert len(items.data) == 1
    assert items.data[0].data.status == "completed"
    assert "diff_preview" not in items.data[0].data.model_dump()


def test_same_action_id_updates_the_existing_audit_item(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(store, conversation.id, _event("approved"))
    _persist_local_action_item(store, conversation.id, _event("completed"))

    items = store.list_items(conversation.id, type="local_action")
    assert len(items.data) == 1
    assert items.data[0].data.status == "completed"


def test_intermediate_local_action_status_is_not_persisted(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(store, conversation.id, _event("requested"))

    assert store.list_items(conversation.id, type="local_action").data == []
