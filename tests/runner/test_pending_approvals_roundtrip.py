"""Round-trip tests for runner pending-approval waits."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from omnigent.runner import pending_approvals


async def _wait_until_pending(conversation_id: str) -> None:
    for _ in range(100):
        if pending_approvals.has_pending(conversation_id):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"approval wait for {conversation_id!r} never registered")


@pytest.fixture(autouse=True)
def _reset_pending_approvals() -> None:
    pending_approvals.reset_for_tests()
    yield
    pending_approvals.reset_for_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize(("approved", "expected"), [(True, True), (False, False)])
async def test_wait_for_user_approval_resolves_from_runner_event_handler(
    approved: bool,
    expected: bool,
) -> None:
    conversation_id = f"conv_pending_{approved}"
    elicitation_id = f"elicit_pending_{approved}"
    published: list[tuple[str, dict[str, Any]]] = []

    task = asyncio.create_task(
        pending_approvals.wait_for_user_approval(
            elicitation_id=elicitation_id,
            conversation_id=conversation_id,
            publish_event=lambda cid, event: published.append((cid, event)),
        )
    )
    await _wait_until_pending(conversation_id)

    assert pending_approvals.resolve(elicitation_id, approved) is True
    assert await asyncio.wait_for(task, timeout=1.0) is expected
    assert pending_approvals.has_pending(conversation_id) is False
    assert published == [
        (
            conversation_id,
            {"type": "response.elicitation_resolved", "elicitation_id": elicitation_id},
        )
    ]


@pytest.mark.asyncio
async def test_wait_for_user_approval_timeout_returns_false_and_resolves_badge() -> None:
    conversation_id = "conv_pending_timeout"
    elicitation_id = "elicit_pending_timeout"
    published: list[tuple[str, dict[str, Any]]] = []

    result = await pending_approvals.wait_for_user_approval(
        elicitation_id=elicitation_id,
        conversation_id=conversation_id,
        publish_event=lambda cid, event: published.append((cid, event)),
        timeout_seconds=0.001,
    )

    assert result is False
    assert pending_approvals.has_pending(conversation_id) is False
    assert published == [
        (
            conversation_id,
            {"type": "response.elicitation_resolved", "elicitation_id": elicitation_id},
        )
    ]
