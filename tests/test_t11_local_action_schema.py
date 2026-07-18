from omnigent.server.schemas import ElicitationRequestParams


def test_legacy_local_action_extras_normalize_to_bounded_nested_payload() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "approve",
            "action_id": "act_write_1",
            "kind": "write_file",
            "policy_mode": "manual",
            "path_summary": ["src/app.py"],
            "diff_preview": "x" * (64 * 1024 + 10),
            "risk_flags": ["writes_files"],
        }
    )
    assert params.local_action is not None
    assert params.local_action.kind == "write_file"
    assert len(params.local_action.diff_preview or "") == 64 * 1024
    assert params.local_action.diff_truncated is True
    dumped = params.model_dump()
    assert "diff_preview" not in dumped
    assert dumped["local_action"]["path_summary"] == ["src/app.py"]


def test_malformed_or_apply_patch_payload_degrades_without_preview() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "apply secret patch",
            "content_preview": "Bearer secret",
            "local_action": {
                "version": 1,
                "action_id": "act_unsupported_1",
                "kind": "apply_patch",
                "policy_mode": "manual",
                "diff_preview": "Bearer secret",
            },
        }
    )
    assert params.local_action is None
    assert params.message == "Approval required for an unsupported local action."
    assert params.content_preview is None
    assert "diff_preview" not in params.model_dump()


def test_shell_preview_requires_explicit_safe_field() -> None:
    params = ElicitationRequestParams.model_validate(
        {
            "message": "approve",
            "action_id": "act_shell_1",
            "kind": "run_shell",
            "policy_mode": "manual",
            "command_summary": "curl -H 'Authorization: Bearer secret'",
            "command_preview": "curl [arguments hidden]",
            "risk_flags": ["shell"],
            "shell_guarantee": "trusted_machine",
        }
    )
    assert params.local_action is not None
    assert params.local_action.command_preview == "curl [arguments hidden]"
    assert "secret" not in str(params.local_action.model_dump())
