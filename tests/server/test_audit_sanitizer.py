from omnigent.server.audit_sanitizer import sanitize_audit_event, sanitize_local_action_history


def test_drops_forbidden_keys_at_top_level() -> None:
    event = {"kind": "write_file", "diff_preview": "secret", "status": "approved"}
    assert sanitize_audit_event(event) == {"kind": "write_file", "status": "approved"}


def test_recurses_into_nested_dicts_and_lists() -> None:
    event = {
        "kind": "run_shell",
        "payload": {"stdout": "secret", "nested": [{"token": "x", "ok": 1}]},
    }
    assert sanitize_audit_event(event) == {
        "kind": "run_shell",
        "payload": {"nested": [{"ok": 1}]},
    }


def test_scalars_and_unknown_keys_pass_through() -> None:
    event = {"kind": "read_file", "path_summary": ["src/a.py"], "duration_s": 0.2}
    assert sanitize_audit_event(event) == event


def test_history_redaction_bounds_and_redacts_string_values() -> None:
    event = {
        "action_id": "act_1",
        "status": "completed",
        "risk_flags": ["prefix-" * 30, "token=super-secret"],
    }

    sanitized = sanitize_local_action_history(event)

    assert sanitized["risk_flags"][0] == ("prefix-" * 30)[:120]  # type: ignore[index]
    assert sanitized["risk_flags"][1] == "[REDACTED]"  # type: ignore[index]
