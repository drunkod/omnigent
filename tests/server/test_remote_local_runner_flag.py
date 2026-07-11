import httpx

from omnigent.db.utils import generate_agent_id
from omnigent.errors import ErrorCode
from omnigent.server.auth import remote_local_runner_enabled
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore


def test_remote_local_runner_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OMNIGENT_REMOTE_LOCAL_RUNNER", raising=False)
    assert remote_local_runner_enabled() is False


def test_remote_local_runner_accepts_truthy_values(monkeypatch) -> None:
    monkeypatch.setenv("OMNIGENT_REMOTE_LOCAL_RUNNER", "true")
    assert remote_local_runner_enabled() is True


async def test_remote_local_runner_policy_is_rejected_when_disabled(
    client: httpx.AsyncClient, db_uri: str, monkeypatch
) -> None:
    agent_id = generate_agent_id()
    SqlAlchemyAgentStore(db_uri).create(
        agent_id, name="test-agent", bundle_location="test:///bundle"
    )
    monkeypatch.delenv("OMNIGENT_REMOTE_LOCAL_RUNNER", raising=False)

    response = await client.post(
        "/v1/sessions",
        json={"agent_id": agent_id, "host_id": "host_test", "local_runner_policy": "manual"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT


async def test_remote_local_runner_policy_requires_a_runner_when_enabled(
    client: httpx.AsyncClient, db_uri: str, monkeypatch
) -> None:
    agent_id = generate_agent_id()
    SqlAlchemyAgentStore(db_uri).create(
        agent_id, name="test-agent", bundle_location="test:///bundle"
    )
    monkeypatch.setenv("OMNIGENT_REMOTE_LOCAL_RUNNER", "true")

    response = await client.post(
        "/v1/sessions",
        json={"agent_id": agent_id, "local_runner_policy": "manual"},
    )
    assert response.status_code == 400
    assert "requires a host or inherited runner" in response.json()["error"]["message"]


async def test_remote_local_runner_policy_is_applied_to_inherited_runner(
    client: httpx.AsyncClient, db_uri: str, monkeypatch
) -> None:
    agent_id = generate_agent_id()
    SqlAlchemyAgentStore(db_uri).create(
        agent_id, name="test-agent", bundle_location="test:///bundle"
    )
    parent = SqlAlchemyConversationStore(db_uri).create_conversation(runner_id="runner_test")
    monkeypatch.setenv("OMNIGENT_REMOTE_LOCAL_RUNNER", "true")

    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent_id,
            "parent_session_id": parent.id,
            "local_runner_policy": "assisted",
        },
    )
    assert response.status_code == 201
    assert response.json()["labels"]["omnigent.local_runner_policy"] == "assisted"
