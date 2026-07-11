from __future__ import annotations

import pytest

from omnigent.policies.builtins.local_runner import (
    LOCAL_RUNNER_PRESETS,
    label_value_for_preset,
    preset_catalog,
)
from omnigent.policies.types import PolicyMode
from omnigent.server.session_binding import resolve_policy_mode_value


def test_every_preset_resolves_to_a_valid_mode() -> None:
    for preset_id in LOCAL_RUNNER_PRESETS:
        assert PolicyMode(label_value_for_preset(preset_id))


def test_catalog_exposes_label_key_and_modes() -> None:
    catalog = preset_catalog()
    assert {entry["preset_id"] for entry in catalog} == set(LOCAL_RUNNER_PRESETS)
    assert all(entry["label_key"] == "omnigent.local_runner_policy" for entry in catalog)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "manual"), ("manual", "manual"), ("assisted", "assisted"), ("local_runner_auto", "auto")],
)
def test_resolve_policy_mode_value(raw: str | None, expected: str) -> None:
    assert resolve_policy_mode_value(raw) == expected


def test_resolve_rejects_unknown_value() -> None:
    with pytest.raises(Exception, match="unknown local runner policy"):
        resolve_policy_mode_value("yolo")
