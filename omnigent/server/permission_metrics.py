"""OpenTelemetry counters for the local-action permission surface."""

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
            description="Local machine actions by kind, status, and policy mode.",
        )
        _approval_decision_total = meter.create_counter(
            "omnigent.approval.decision_total",
            description="Local-action approval decisions.",
        )
    return _local_action_total, _approval_decision_total


def record_local_action(kind: str, status: str, policy_mode: str) -> None:
    action_total, _ = _counters()
    action_total.add(1, {"kind": kind, "status": status, "policy_mode": policy_mode})


def record_approval_decision(approved: bool) -> None:
    decision_total = _counters()[1]
    decision_total.add(1, {"decision": "approved" if approved else "denied"})
