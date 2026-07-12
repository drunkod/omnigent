"""T12 control-mode acceptance tests over a real runner tunnel and tmux."""

from __future__ import annotations

import asyncio

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
    async with terminal_tunnel.connect(transport="control") as conn:
        initial = await _receive_until(conn, b"T12_READY")
        assert initial.count(b"T12_READY") == 1

        await conn.send(b"hello from browser\n")
        echoed = await _receive_until(conn, b"T12_ECHO:hello from browser")

    combined = initial + echoed
    assert combined.count(b"T12_READY") == 1
    assert combined.count(b"T12_ECHO:hello from browser") == 1
