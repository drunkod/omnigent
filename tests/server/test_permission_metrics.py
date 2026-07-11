from __future__ import annotations

from opentelemetry import metrics as otel_metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import omnigent.server.permission_metrics as permission_metrics


def test_permission_counters_record_bounded_labels(monkeypatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(otel_metrics, "get_meter", provider.get_meter)
    monkeypatch.setattr(permission_metrics, "_local_action_total", None)
    monkeypatch.setattr(permission_metrics, "_approval_decision_total", None)

    permission_metrics.record_local_action("write_file", "blocked", "manual")
    permission_metrics.record_approval_decision(True)

    metrics = reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics
    assert {metric.name for metric in metrics} == {
        "omnigent.local_action.total",
        "omnigent.approval.decision_total",
    }
