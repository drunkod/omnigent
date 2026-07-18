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


async def _wait_for_terminal_exit(
    terminal_tunnel: TerminalTunnelFixture,
    *,
    timeout: float = 5.0,
) -> None:
    """Wait until the fixture's foreground terminal process is no longer alive."""
    entries = terminal_tunnel.terminal_registry.list_for_conversation(terminal_tunnel.session_id)
    assert len(entries) == 1
    async with asyncio.timeout(timeout):
        while await entries[0].instance.is_alive():
            await asyncio.sleep(0.02)


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

        async with connect(
            terminal_tunnel.url(),
            additional_headers={"X-Forwarded-Email": "owner@example.com"},
        ) as owner:
            initial = await _receive_until(owner, b"T12_READY")
            await owner.send(b"owner-barrier\n")
            echoed = await _receive_until(owner, b"T12_ECHO:owner-barrier")

    assert b"T12_ECHO:must-not-execute" not in initial + echoed


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
    lines = [
        "first",
        "wide:界🙂",
        *(f"chunk-{index}:" + "x" * 512 for index in range(12)),
        "last",
    ]
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


async def test_control_key_sequences_arrive_byte_exact(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """ESC, arrows, tab, backspace, and Enter survive the control tunnel exactly."""
    sequence = b"\x1b[A\x1b[B\x1b[C\x1b[D\x1b\t\x7f\r"
    marker = b"T12_RAW_HEX:" + sequence.hex().encode()

    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(b"T12_RAW\n")
        await _receive_until(conn, b"T12_RAW_READY")
        await conn.send(sequence + b"\x04")
        output = await _receive_until(conn, marker)

    assert output.count(marker) == 1


async def test_ctrl_c_interrupts_foreground_process(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A browser Ctrl-C reaches the pane's foreground process as SIGINT."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(b"\x03")
        await _wait_for_terminal_exit(terminal_tunnel)


async def test_alternate_screen_enter_and_exit_bytes_are_forwarded(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Control mode preserves alternate-screen enter and exit sequences in order."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(b"T12_ALTSCREEN\n")
        output = await _receive_until(conn, b"T12_ALT_EXIT")

    markers = [
        b"\x1b[?1049h",
        b"T12_ALT_ENTER",
        b"\x1b[?1049l",
        b"T12_ALT_EXIT",
    ]
    positions = [output.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert all(output.count(marker) == 1 for marker in markers)


async def test_rapid_output_remains_ordered_and_bounded(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A deterministic burst crosses the bridge once, in order, within a fixed bound."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await _receive_until(conn, b"T12_READY")
        await conn.send(b"T12_BURST\n")
        output = await _receive_until(conn, b"T12_BURST:0255:", timeout=10.0)

    positions = []
    for index in range(256):
        marker = f"T12_BURST:{index:04d}:".encode()
        assert output.count(marker) == 1
        positions.append(output.index(marker))
    assert positions == sorted(positions)
    assert len(output) < 128 * 1024
