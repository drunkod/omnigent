"""T01 hello capability extension tests."""

from __future__ import annotations

import json

import pytest

from omnigent.runner.transports.ws_tunnel.capabilities import (
    DEFAULT_TOOL_CAPABILITIES,
    build_hello,
    detect_terminal_transports,
)
from omnigent.runner.transports.ws_tunnel.frames import (
    FRAME_PROTOCOL_VERSION,
    HelloFrame,
    decode_frame,
    encode_frame,
)


def test_new_hello_roundtrip() -> None:
    frame = HelloFrame(
        runner_version="0.9.0",
        frame_protocol_version=FRAME_PROTOCOL_VERSION,
        harnesses=["codex", "claude-native"],
        envs=["os_sandbox"],
        mode="local",
        os_name="darwin",
        arch="arm64",
        workspace_roots=[
            {
                "workspace_id": "ws_abc123",
                "display_name": "omnigent",
                "path_label": "~/projects/omnigent",
                "capabilities": ["read", "write", "shell", "git", "terminal"],
            }
        ],
        terminal_transports=["pty", "control"],
        tool_capabilities=["read_file", "run_shell"],
    )

    decoded = decode_frame(encode_frame(frame))

    assert decoded == frame


def test_old_runner_hello_decodes_with_defaults() -> None:
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.1.2",
            "frame_protocol_version": FRAME_PROTOCOL_VERSION,
            "harnesses": ["codex"],
            "envs": ["os_sandbox"],
        }
    )

    hello = decode_frame(wire)

    assert isinstance(hello, HelloFrame)
    assert hello.mode is None
    assert hello.os_name is None
    assert hello.arch is None
    assert hello.workspace_roots == []
    assert hello.terminal_transports == []
    assert hello.tool_capabilities == []


def test_unknown_extra_fields_are_ignored() -> None:
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.9.0",
            "frame_protocol_version": FRAME_PROTOCOL_VERSION,
            "harnesses": [],
            "envs": [],
            "some_future_field": {"x": 1},
        }
    )

    hello = decode_frame(wire)

    assert isinstance(hello, HelloFrame)


def test_malformed_capability_fields_do_not_reject_tunnel() -> None:
    wire = json.dumps(
        {
            "kind": "hello",
            "runner_version": "0.9.0",
            "frame_protocol_version": FRAME_PROTOCOL_VERSION,
            "harnesses": [],
            "envs": [],
            "mode": "unexpected",
            "os_name": 123,
            "arch": False,
            "workspace_roots": [
                {"workspace_id": "ws_ok"},
                "bad",
                4,
            ],
            "terminal_transports": ["pty", 123, "control"],
            "tool_capabilities": "read_file",
        }
    )

    hello = decode_frame(wire)

    assert isinstance(hello, HelloFrame)
    assert hello.mode is None
    assert hello.os_name is None
    assert hello.arch is None
    assert hello.workspace_roots == [{"workspace_id": "ws_ok"}]
    assert hello.terminal_transports == ["pty", "control"]
    assert hello.tool_capabilities == []


def test_detect_terminal_transports_requires_tmux_and_supported_platform() -> None:
    assert detect_terminal_transports(system="linux", tmux_available=True) == [
        "pty",
        "control",
    ]
    assert detect_terminal_transports(system="darwin", tmux_available=True) == [
        "pty",
        "control",
    ]
    assert detect_terminal_transports(system="linux", tmux_available=False) == []
    assert detect_terminal_transports(system="windows", tmux_available=True) == []


def test_detect_terminal_transports_honors_feature_flags() -> None:
    assert detect_terminal_transports(
        system="linux",
        tmux_available=True,
        feature_flags={"terminal-control"},
    ) == ["control"]
    assert (
        detect_terminal_transports(
            system="linux",
            tmux_available=True,
            feature_flags=set(),
        )
        == []
    )


class _WorkspaceRegistry:
    def advertise(self) -> list[dict[str, object]]:
        return [
            {
                "workspace_id": "ws_123",
                "display_name": "demo",
                "path_label": "~/demo",
                "capabilities": ["read", "write"],
            }
        ]


def test_build_hello_populates_capability_fields() -> None:
    hello = build_hello(
        runner_version="1.2.3",
        harnesses=["codex"],
        envs=["os_sandbox"],
        mode="local",
        workspace_registry=_WorkspaceRegistry(),
        system="linux",
        tmux_available=True,
    )

    assert hello.runner_version == "1.2.3"
    assert hello.frame_protocol_version == FRAME_PROTOCOL_VERSION
    assert hello.harnesses == ["codex"]
    assert hello.envs == ["os_sandbox"]
    assert hello.mode == "local"
    assert hello.os_name
    assert hello.arch
    assert hello.workspace_roots[0]["workspace_id"] == "ws_123"
    assert hello.terminal_transports == ["pty", "control"]
    assert hello.tool_capabilities == DEFAULT_TOOL_CAPABILITIES
    assert "search_files" not in hello.tool_capabilities
    assert "git_status" not in hello.tool_capabilities
    assert "git_diff" not in hello.tool_capabilities
    assert "apply_patch" not in hello.tool_capabilities


def test_build_hello_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="unsupported runner mode"):
        build_hello(
            runner_version="1.2.3",
            harnesses=[],
            envs=[],
            mode="locale",
            system="linux",
            tmux_available=True,
        )
