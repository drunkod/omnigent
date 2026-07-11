# Step 01 — Policy presets and label application

Goal: three named presets a user can pick in the UI/API, each resolving at
selection time to a raw `PolicyMode` value stored in the
`omnigent.local_runner_policy` session label. The runner already reads that
label per action and re-classifies independently (defense in depth), so this
step is server-side only.

## 1. New module — `omnigent/policies/builtins/local_runner.py`

These presets are label conveniences, not policy callables, so the module
exports a catalog plus resolver instead of a `POLICY_REGISTRY` evaluator.

```python
"""Built-in policy presets for remote-local runner sessions.

Presets are UI/API conveniences only: applying a preset resolves to a raw
:class:`PolicyMode` string stored in the ``omnigent.local_runner_policy``
session label. The runner reads that raw mode with every local action and
independently re-checks classification (defense in depth): a compromised or
stale server cannot grant more than the runner's own blocklist allows.
"""

from __future__ import annotations

from omnigent.policies.types import PolicyMode
from omnigent.server.session_binding import LOCAL_RUNNER_POLICY_LABEL_KEY

DEFAULT_LOCAL_RUNNER_MODE = PolicyMode.MANUAL

# Preset id → (PolicyMode, human description). Preset ids are API/UI
# contract, but are resolved at label-write time; the label stores raw
# PolicyMode values so old sessions never depend on preset ids.
LOCAL_RUNNER_PRESETS: dict[str, tuple[PolicyMode, str]] = {
    "local_runner_manual": (
        PolicyMode.MANUAL,
        "Ask before every file write and shell command. Reads inside the "
        "workspace are allowed. Recommended default.",
    ),
    "local_runner_assisted": (
        PolicyMode.ASSISTED,
        "Reads, listing, search, git status/diff are allowed. Writes, "
        "patches, and shell commands ask first.",
    ),
    "local_runner_auto": (
        PolicyMode.AUTO,
        "Writes and shell inside the workspace are allowed. Package "
        "installs, destructive git, file removal, and anything risky "
        "still asks. Workspace escapes are always blocked.",
    ),
}


def label_value_for_preset(preset_id: str) -> str:
    """Resolve a preset id to the raw label value.

    :param preset_id: One of :data:`LOCAL_RUNNER_PRESETS`.
    :returns: The ``PolicyMode`` string value, e.g. ``"manual"``.
    :raises KeyError: Unknown preset id — callers translate to a 400.
    """

    return LOCAL_RUNNER_PRESETS[preset_id][0].value


def preset_catalog() -> list[dict[str, str]]:
    """Public catalog for the presets API/UI listing."""

    return [
        {
            "preset_id": preset_id,
            "mode": mode.value,
            "description": description,
            "label_key": LOCAL_RUNNER_POLICY_LABEL_KEY,
        }
        for preset_id, (mode, description) in LOCAL_RUNNER_PRESETS.items()
    ]
```

Import caution (from the T08 plan): keep this module importing only
`omnigent.policies.types` and `omnigent.server.session_binding` — never
`omnigent.runner.workspace_policy` — so server policy code doesn't import
runner execution modules. If the `session_binding` import creates a cycle,
inline the key string with a comment pointing at the constant.

## 2. Apply-preset in session create / update

Session create already merges binding labels in
`omnigent/server/session_binding.py` (see `merged[EXECUTION_MODE_LABEL_KEY]`
around line 105). Extend the request handling so callers can pass either a
raw mode or a preset id:

```python
# session_binding.py — add near the existing label helpers
from omnigent.policies.types import PolicyMode


def resolve_policy_mode_value(raw: str | None) -> str:
    """Normalize a request's policy field to a raw label value.

    Accepts a preset id (``local_runner_manual``) or a raw mode
    (``manual``). ``None`` → the MANUAL default. Anything else raises.
    """

    from omnigent.policies.builtins.local_runner import (
        DEFAULT_LOCAL_RUNNER_MODE,
        LOCAL_RUNNER_PRESETS,
    )

    if raw is None:
        return DEFAULT_LOCAL_RUNNER_MODE.value
    if raw in LOCAL_RUNNER_PRESETS:
        return LOCAL_RUNNER_PRESETS[raw][0].value
    try:
        return PolicyMode(raw).value
    except ValueError:
        raise OmnigentError(
            f"unknown local runner policy {raw!r}",
            code=ErrorCode.INVALID_REQUEST,
        ) from None
```

Then in the create-session path where local-runner labels are merged:

```python
merged[LOCAL_RUNNER_POLICY_LABEL_KEY] = resolve_policy_mode_value(
    body.get("local_runner_policy")
)
```

Changing the label later affects only **future** actions — no revocation of
an in-flight approval; document this in the route docstring.

## 3. Expose the catalog

Smallest MVP: include `preset_catalog()` in the existing policies listing
route response (or a `GET /v1/local-runner-policies` if the registry route
is strictly handler-shaped). The UI picker for T07b/Deferred B reads it.

## 4. Tests — `tests/server/test_local_runner_presets.py`

```python
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
    assert {c["preset_id"] for c in catalog} == set(LOCAL_RUNNER_PRESETS)
    assert all(c["label_key"] == "omnigent.local_runner_policy" for c in catalog)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "manual"),
        ("manual", "manual"),
        ("assisted", "assisted"),
        ("local_runner_auto", "auto"),
    ],
)
def test_resolve_policy_mode_value(raw: str | None, expected: str) -> None:
    assert resolve_policy_mode_value(raw) == expected


def test_resolve_rejects_unknown_value() -> None:
    with pytest.raises(Exception):
        resolve_policy_mode_value("yolo")
```

Runner-side fallback (unknown label → MANUAL) is already covered by
`tests/runner/test_local_runner_policy_binding.py` — add a case there only
if one doesn't already assert the invalid-string path.
