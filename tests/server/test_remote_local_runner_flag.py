from omnigent.server.auth import remote_local_runner_enabled


def test_remote_local_runner_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OMNIGENT_REMOTE_LOCAL_RUNNER", raising=False)
    assert remote_local_runner_enabled() is False


def test_remote_local_runner_accepts_truthy_values(monkeypatch) -> None:
    monkeypatch.setenv("OMNIGENT_REMOTE_LOCAL_RUNNER", "true")
    assert remote_local_runner_enabled() is True
