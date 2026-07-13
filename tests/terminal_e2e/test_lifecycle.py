"""T12 lifecycle acceptance tests at the public terminal attach boundary."""

from __future__ import annotations

import asyncio

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from omnigent.runner.transports.ws_tunnel.frames import WSCloseFrame
from tests.terminal_e2e.conftest import TerminalTunnelFixture


async def _wait_for_close(conn, *, timeout: float = 5.0) -> ConnectionClosed:
    """Receive until the peer closes and return the observed close."""
    try:
        async with asyncio.timeout(timeout):
            while True:
                await conn.recv()
    except ConnectionClosed as exc:
        return exc
    raise AssertionError("terminal WebSocket did not close")


async def _receive_until(conn, marker: bytes, *, timeout: float = 5.0) -> bytes:
    """Collect terminal output until a deterministic marker arrives."""
    output = bytearray()
    async with asyncio.timeout(timeout):
        while marker not in output:
            frame = await conn.recv()
            assert isinstance(frame, bytes)
            output.extend(frame)
    return bytes(output)


async def test_runner_tunnel_drop_closes_attach_as_runner_offline(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Losing the runner tunnel reports 4503 while preserving the tmux pane."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await conn.recv()
        await terminal_tunnel.disconnect_runner()
        closed = await _wait_for_close(conn)

    assert closed.rcvd is not None
    assert closed.rcvd.code == 4503
    entries = terminal_tunnel.terminal_registry.list_for_conversation(terminal_tunnel.session_id)
    assert len(entries) == 1
    assert await entries[0].instance.is_alive()


async def test_terminal_exit_closes_attach_as_terminal_exited(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Killing tmux reports 4404 while the runner tunnel remains online."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await conn.recv()
        await terminal_tunnel.close_terminal()
        closed = await _wait_for_close(conn)

    assert closed.rcvd is not None
    assert closed.rcvd.code == 4404
    assert terminal_tunnel.tunnel_registry.get(terminal_tunnel.runner_id) is not None


async def test_unsupported_transport_closes_without_disturbing_runner_or_tmux(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """An unsupported attach transport reports 4406 without killing session state."""
    async with connect(
        terminal_tunnel.url(transport="unsupported"),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        closed = await _wait_for_close(conn)

    assert closed.rcvd is not None
    assert closed.rcvd.code == 4406
    assert terminal_tunnel.tunnel_registry.get(terminal_tunnel.runner_id) is not None
    entries = terminal_tunnel.terminal_registry.list_for_conversation(terminal_tunnel.session_id)
    assert len(entries) == 1
    assert await entries[0].instance.is_alive()


async def test_same_runner_reconnect_reattaches_without_duplicate_io(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """A new tunnel generation preserves tmux and replays each marker once."""
    headers = {"X-Forwarded-Email": "owner@example.com"}
    async with connect(terminal_tunnel.url(), additional_headers=headers) as first:
        await _receive_until(first, b"T12_READY")
        await first.send(b"before-reconnect\n")
        before = await _receive_until(first, b"T12_ECHO:before-reconnect")
        assert before.count(b"T12_ECHO:before-reconnect") == 1
        await terminal_tunnel.disconnect_runner()
        closed = await _wait_for_close(first)
        assert closed.rcvd is not None and closed.rcvd.code == 4503

    terminal_tunnel.reconnect_runner()
    async with connect(terminal_tunnel.url(), additional_headers=headers) as second:
        replay = await _receive_until(second, b"T12_ECHO:before-reconnect")
        assert replay.count(b"T12_READY") == 1
        assert replay.count(b"T12_ECHO:before-reconnect") == 1
        await second.send(b"after-reconnect\n")
        after = await _receive_until(second, b"T12_ECHO:after-reconnect")
        assert after.count(b"T12_ECHO:after-reconnect") == 1


async def test_stale_generation_close_cannot_cover_live_reconnected_terminal(
    terminal_tunnel: TerminalTunnelFixture,
    monkeypatch,
) -> None:
    """A late close from the retired generation cannot tear down the new attach."""

    class _FixedSecrets:
        @staticmethod
        def token_hex(_length: int) -> str:
            return "deadbeef"

    monkeypatch.setattr("omnigent.server._runner_ws_tunnel.secrets", _FixedSecrets())
    headers = {"X-Forwarded-Email": "owner@example.com"}

    async with connect(terminal_tunnel.url(), additional_headers=headers) as first:
        await _receive_until(first, b"T12_READY")
        retired = await terminal_tunnel.disconnect_runner()
        closed = await _wait_for_close(first)
        assert closed.rcvd is not None and closed.rcvd.code == 4503

    terminal_tunnel.reconnect_runner()
    async with connect(terminal_tunnel.url(), additional_headers=headers) as second:
        await _receive_until(second, b"T12_READY")
        current = terminal_tunnel.tunnel_registry.get(terminal_tunnel.runner_id)
        assert current is not None
        assert "deadbeef" in current.ws_channels

        delivered = terminal_tunnel.tunnel_registry.route_ws_inbound(
            terminal_tunnel.runner_id,
            WSCloseFrame(ch_id="deadbeef", code=4404, reason="stale terminal exit"),
            session=retired,
        )
        assert delivered is False

        await second.send(b"still-live-after-stale-close\n")
        output = await _receive_until(second, b"T12_ECHO:still-live-after-stale-close")
        assert output.count(b"T12_ECHO:still-live-after-stale-close") == 1
