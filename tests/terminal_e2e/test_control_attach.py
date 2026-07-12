"""T12 control-mode acceptance tests over a real runner tunnel and tmux."""

from __future__ import annotations

import asyncio

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from tests.terminal_e2e.conftest import TerminalTunnelFixture


async def _receive_until(conn, marker: bytes, *, timeout: float = 5.0) -> bytes:
    """Collect terminal frames until *marker* arrives or fail on timeout."""
    output = bytearray()
    async with asyncio.timeout(timeout):
        while marker not in output:
            frame = await conn.recv()
            assert isinstance(frame, bytes)
            output.extend(frame)
    return bytes(output)


async def test_control_attach_initial_capture_and_input_round_trip(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Initial tmux output appears once and browser-shaped input reaches the pane."""
    async with connect(
        terminal_tunnel.url(transport="control"),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        initial = await _receive_until(conn, b"T12_READY")
        assert initial.count(b"T12_READY") == 1

        await conn.send(b"hello from browser\n")
        echoed = await _receive_until(conn, b"T12_ECHO:hello from browser")

    combined = initial + echoed
    assert combined.count(b"T12_READY") == 1
    assert combined.count(b"T12_ECHO:hello from browser") == 1


async def test_read_only_collaborator_observes_but_cannot_drive_terminal(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A read collaborator sees output while attempted input has no side effect."""
    async with connect(
        terminal_tunnel.url(read_only=True),
        additional_headers={"X-Forwarded-Email": "viewer@example.com"},
    ) as viewer:
        output = await _receive_until(viewer, b"T12_READY")
        assert b"T12_READY" in output
        await viewer.send(b"must-not-execute\n")
        await asyncio.sleep(0.2)

    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as owner:
        output = await _receive_until(owner, b"T12_READY")
        assert b"T12_ECHO:must-not-execute" not in output


async def test_read_collaborator_cannot_open_interactive_attach(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Authorization rejects collaborator input before opening a runner channel."""
    with pytest.raises(InvalidStatus) as exc_info:
        async with connect(
            terminal_tunnel.url(),
            additional_headers={"X-Forwarded-Email": "viewer@example.com"},
        ):
            pass
    assert exc_info.value.response.status_code == 403
