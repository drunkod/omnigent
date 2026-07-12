"""T12 lifecycle acceptance tests at the public terminal attach boundary."""

from __future__ import annotations

import asyncio

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

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


async def test_runner_tunnel_drop_closes_attach_as_runner_offline(
    terminal_tunnel: TerminalTunnelFixture,
) -> None:
    """Losing the runner tunnel reports 4503 while preserving the tmux pane."""
    async with connect(
        terminal_tunnel.url(),
        additional_headers={"X-Forwarded-Email": "owner@example.com"},
    ) as conn:
        await conn.recv()
        terminal_tunnel.disconnect_runner()
        closed = await _wait_for_close(conn)

    assert closed.rcvd is not None
    assert closed.rcvd.code == 4503
    entries = terminal_tunnel.terminal_registry.list_for_conversation(
        terminal_tunnel.session_id
    )
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
