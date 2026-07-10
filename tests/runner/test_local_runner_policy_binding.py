"""Tests for local-runner policy-mode labels in runner dispatch."""

from __future__ import annotations

import httpx
import pytest

from omnigent.policies.types import PolicyMode
from omnigent.runner.tool_dispatch import (
    _local_runner_workspace_binding,
    reset_local_runner_binding_cache,
)


@pytest.fixture(autouse=True)
def _reset_binding_cache() -> None:
    reset_local_runner_binding_cache()
    yield
    reset_local_runner_binding_cache()


class _SessionClient:
    def __init__(self, labels: dict[str, str]) -> None:
        self._labels = labels

    async def get(self, path: str, timeout: float | None = None) -> httpx.Response:
        del path, timeout
        return httpx.Response(200, json={"labels": self._labels})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_mode", "expected"),
    [
        (PolicyMode.MANUAL.value, PolicyMode.MANUAL),
        (PolicyMode.ASSISTED.value, PolicyMode.ASSISTED),
        (PolicyMode.AUTO.value, PolicyMode.AUTO),
    ],
)
async def test_local_runner_binding_reads_raw_policy_mode_label_values(
    raw_mode: str,
    expected: PolicyMode,
) -> None:
    conversation_id = f"conv_raw_policy_{raw_mode}"

    binding = await _local_runner_workspace_binding(
        _SessionClient(
            {
                "omnigent.execution_mode": "local_runner",
                "omnigent.workspace_id": "ws_abc123",
                "omnigent.local_runner_policy": raw_mode,
            }
        ),
        conversation_id,
    )

    assert binding.status == "bound"
    assert binding.workspace_id == "ws_abc123"
    assert binding.mode is expected


@pytest.mark.asyncio
async def test_local_runner_binding_invalid_policy_mode_falls_back_to_manual() -> None:
    conversation_id = "conv_raw_policy_invalid"

    binding = await _local_runner_workspace_binding(
        _SessionClient(
            {
                "omnigent.execution_mode": "local_runner",
                "omnigent.workspace_id": "ws_abc123",
                "omnigent.local_runner_policy": "local_runner_auto",
            }
        ),
        conversation_id,
    )

    assert binding.status == "bound"
    assert binding.workspace_id == "ws_abc123"
    assert binding.mode is PolicyMode.MANUAL
