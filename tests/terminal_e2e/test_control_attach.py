"""T12 control-mode acceptance tests over a real runner tunnel and tmux."""

from __future__ import annotations

import asyncio
import json

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


async def test_resize_reaches_terminal_process(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A browser resize changes tmux dimensions observed by the pane process."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(json.dumps({"type": "resize", "cols": 101, "rows": 37}))
        output = await _receive_until(conn, b"T12_SIZE:101x37")
    assert output.count(b"T12_SIZE:101x37") == 1


async def test_multiline_utf8_paste_arrives_once_and_in_order(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A browser paste preserves line order, UTF-8, and wide characters."""
    lines = ["first", "wide:界🙂", *(f"chunk-{index}:" + "x" * 512 for index in range(12)), "last"]
    payload = ("\n".join(lines) + "\n").encode()

    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(payload)
        output = await _receive_until(conn, b"T12_ECHO:last")

    positions = []
    for line in lines:
        marker = b"T12_ECHO:" + line.encode()
        assert output.count(marker) == 1
        positions.append(output.index(marker))
    assert positions == sorted(positions)
    assert "界🙂".encode() in output
