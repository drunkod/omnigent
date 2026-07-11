# Step 07 — Permission telemetry wiring

Closes the P11 counters relevant to permissions. The metrics subsystem is a
publisher object (`omnigent/server/performance_metrics.py`, `create_counter`
at ~L138, meter resolution at ~L915), not a global registry — the earlier
attempt correctly deferred rather than double-counting. The clean shape is a
small module-level metrics holder initialized once, imported by the two
emission sites.

## 1. Counter holder — `omnigent/server/permission_metrics.py`

```python
"""OpenTelemetry counters for the local-action permission surface.

Module-level lazy singletons: the meter is resolved on first use, matching
how ``performance_metrics`` resolves ``otel_metrics.get_meter``. Counters
are cheap and process-global, so no publisher threading is needed — unlike
the periodic gauge publisher, these are event-driven increments.
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics

_METER_NAME = "omnigent.permissions"

_local_action_total = None
_approval_decision_total = None


def _counters():
    global _local_action_total, _approval_decision_total
    if _local_action_total is None:
        meter = otel_metrics.get_meter(_METER_NAME)
        _local_action_total = meter.create_counter(
            "omnigent.local_action.total",
            description="Local machine actions by kind/status/policy_mode",
        )
        _approval_decision_total = meter.create_counter(
            "omnigent.approval.decision_total",
            description="Local-action approval decisions",
        )
    return _local_action_total, _approval_decision_total


def record_local_action(kind: str, status: str, policy_mode: str) -> None:
    """One increment per audit status transition."""

    action_total, _ = _counters()
    action_total.add(1, {"kind": kind, "status": status, "policy_mode": policy_mode})


def record_approval_decision(approved: bool) -> None:
    decision_total = _counters()[1]
    decision_total.add(1, {"decision": "approved" if approved else "denied"})
```

## 2. Emission sites (both already exist as code paths)

**Local actions — the SSE relay**, next to the sanitizer/persistence hook
(one increment per status transition; the runner's audit stream is the
single source of truth, so counting here can't double-count):

```python
# sessions.py relay loop, inside the session.local_action branch
from omnigent.server.permission_metrics import record_local_action

record_local_action(
    kind=str(event.get("kind", "unknown")),
    status=str(event.get("status", "unknown")),
    policy_mode=str(event.get("policy_mode", "unknown")),
)
```

**Approval decisions — `_resolve_elicitation`**, after the owner gate,
only for tagged local actions:

```python
if local_action_session == session_id:
    ...owner gate...
    from omnigent.server.permission_metrics import record_approval_decision

    record_approval_decision(data.get("action") == "accept")
```

Verify the accept/decline field name against what the resolution handler
actually receives (`action: "accept"` is what the gate tests use).

## 3. Tests — `tests/server/test_permission_metrics.py`

OpenTelemetry counters can be asserted with the in-memory reader:

```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry import metrics as otel_metrics

import omnigent.server.permission_metrics as pm


def test_counters_record_labels(monkeypatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(otel_metrics, "get_meter", provider.get_meter)
    # reset lazy singletons so they bind to the test provider
    monkeypatch.setattr(pm, "_local_action_total", None)
    monkeypatch.setattr(pm, "_approval_decision_total", None)

    pm.record_local_action("write_file", "blocked", "manual")
    pm.record_approval_decision(True)

    metrics = reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics
    names = {m.name for m in metrics}
    assert "omnigent.local_action.total" in names
    assert "omnigent.approval.decision_total" in names
```

## Log hygiene reminder

No file contents, command output, tokens, or absolute home paths in metric
labels or logs — labels above are enum-like strings only. `kind`, `status`,
`policy_mode`, `decision` are all bounded sets, so cardinality is safe.

## Done when

- Both counters visible via the OTel pipeline in a dev run.
- Relay and resolution emission covered by the unit test.
- P11 rows for `local_action.total` / `approval.decision_total` checkable
  (tunnel/attach counters remain a separate later slice).
