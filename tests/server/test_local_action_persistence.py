from __future__ import annotations

from omnigent.server.audit_sanitizer import sanitize_audit_event
from omnigent.server.routes.sessions import _persist_local_action_item
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore


def _event(status: str, *, action_id: str = "act_1", **extra: object) -> dict[str, object]:
    return {
        "type": "session.local_action",
        "action_id": action_id,
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
        sanitize_audit_event(
            _event(
                "completed",
                diff_preview="SECRET",
                command_summary="curl -H 'Authorization: Bearer super-secret' https://x",
                path_summary=["/Users/alice/.ssh/id_ed25519", "src/main.py"],
                stdout="private output",
            )
        ),
    )

    items = store.list_items(conversation.id, type="local_action")
    assert len(items.data) == 1
    assert items.data[0].data.status == "completed"
    persisted = items.data[0].data.model_dump()
    assert "diff_preview" not in persisted
    assert "command" not in persisted
    assert "content" not in persisted
    assert persisted["command_summary"] == "curl"
    assert persisted["path_summary"] == ["src/main.py"]
    assert "super-secret" not in str(persisted)
    assert "/Users/alice" not in str(persisted)


def test_same_action_id_updates_the_existing_audit_item(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(store, conversation.id, _event("approved"))
    _persist_local_action_item(store, conversation.id, _event("completed"))

    items = store.list_items(conversation.id, type="local_action")
    assert len(items.data) == 1
    assert items.data[0].data.status == "completed"


def test_action_id_is_matched_as_an_exact_response_id(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(store, conversation.id, _event("approved", action_id="act_%_1"))
    _persist_local_action_item(store, conversation.id, _event("completed", action_id="act_%_1"))
    _persist_local_action_item(store, conversation.id, _event("denied", action_id="act_other"))

    items = store.list_items(conversation.id, type="local_action")
    assert len(items.data) == 2
    by_action = {item.data.action_id: item.data.status for item in items.data}
    assert by_action == {"act_%_1": "completed", "act_other": "denied"}


def test_intermediate_local_action_status_is_not_persisted(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    conversation = store.create_conversation()
    _persist_local_action_item(store, conversation.id, _event("requested"))

    assert store.list_items(conversation.id, type="local_action").data == []
