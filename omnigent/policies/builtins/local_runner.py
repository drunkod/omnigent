"""Named policy presets for local-runner sessions.

Presets resolve to raw ``PolicyMode`` values stored in session labels. The
runner still classifies every action independently and remains authoritative.
"""

from __future__ import annotations

from omnigent.policies.types import LOCAL_RUNNER_POLICY_LABEL_KEY, PolicyMode

DEFAULT_LOCAL_RUNNER_MODE = PolicyMode.MANUAL

LOCAL_RUNNER_PRESETS: dict[str, tuple[PolicyMode, str]] = {
    "local_runner_manual": (
        PolicyMode.MANUAL,
        "Ask before every local write or shell command.",
    ),
    "local_runner_assisted": (
        PolicyMode.ASSISTED,
        "Allow reads and ask before local writes or shell commands.",
    ),
    "local_runner_auto": (
        PolicyMode.AUTO,
        "Allow safe workspace writes and shell commands; risky actions still ask.",
    ),
}


def label_value_for_preset(preset_id: str) -> str:
    """Resolve a public preset id to its raw label value."""

    return LOCAL_RUNNER_PRESETS[preset_id][0].value


def preset_catalog() -> list[dict[str, str]]:
    """Return the stable catalog consumed by API and UI clients."""

    return [
        {
            "preset_id": preset_id,
            "mode": mode.value,
            "description": description,
            "label_key": LOCAL_RUNNER_POLICY_LABEL_KEY,
        }
        for preset_id, (mode, description) in LOCAL_RUNNER_PRESETS.items()
    ]
