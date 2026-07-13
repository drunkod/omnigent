from omnigent.server import _runner_state_registry


def test_runner_state_registry_roundtrip_is_copy_safe() -> None:
    _runner_state_registry.reset_for_tests()
    event = {"type": "session.runner_state", "state": "runner_offline"}
    _runner_state_registry.record("conv_a", event)

    snapshot = _runner_state_registry.snapshot("conv_a")
    assert snapshot == event
    assert snapshot is not event
    assert _runner_state_registry.snapshot("conv_b") is None

    _runner_state_registry.clear("conv_a")
    assert _runner_state_registry.snapshot("conv_a") is None
