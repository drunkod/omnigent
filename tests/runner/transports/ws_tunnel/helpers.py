"""Shared in-memory harness for runner WebSocket tunnel tests."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import FastAPI

from omnigent.runner.transports.ws_tunnel.frames import (
    HelloFrame,
    WSCloseFrame,
    WSFrame,
    decode_frame,
)
from omnigent.runner.transports.ws_tunnel.registry import TunnelRegistry
from omnigent.runner.transports.ws_tunnel.serve import (
    _cancel_ws_channels,
    _handle_tunnel_frame,
    _RunnerWSChannel,
)


class LoopbackWebSocket:
    """One half of an in-memory runner tunnel WebSocket pair."""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[str] = asyncio.Queue()
        self.peer: LoopbackWebSocket | None = None

    def link(self, peer: LoopbackWebSocket) -> None:
        self.peer = peer
        peer.peer = self

    async def send_text(self, data: str) -> None:
        assert self.peer is not None
        await self.peer.inbound.put(data)

    async def receive_text(self) -> str:
        return await self.inbound.get()


@dataclass
class TunnelHarness:
    """A live server/runner tunnel pair backed by an ASGI runner app."""

    registry: TunnelRegistry
    runner_id: str
    ws_channels: dict[str, _RunnerWSChannel]
    _server_ws: LoopbackWebSocket
    _hello: HelloFrame
    _tasks: list[asyncio.Task[None]]
    _dispatch_tasks: dict[str, asyncio.Task[None]]

    async def disconnect(self) -> None:
        """Retire both server and runner state for the active tunnel generation."""
        session = self.registry.get(self.runner_id)
        assert session is not None
        self.registry.deregister(self.runner_id, session=session)
        await _cancel_ws_channels(self.ws_channels)
        self.ws_channels.clear()

    def reconnect(self) -> None:
        """Register a new server-side generation on the existing runner transport."""
        session = self.registry.register(self.runner_id, self._server_ws, self._hello)

        async def send_server_frames() -> None:
            while True:
                data = await session.outbound_queue.get()
                if data is None:
                    return
                await session.ws.send_text(data)

        self._tasks.append(asyncio.create_task(send_server_frames(), name="tunnel-reconnect-send"))


@contextlib.asynccontextmanager
async def run_tunnel_harness(
    runner_app: FastAPI,
    *,
    runner_id: str,
    hello: HelloFrame,
) -> AsyncIterator[TunnelHarness]:
    """Run both ends of the multiplexed tunnel on the current event loop."""
    server_ws = LoopbackWebSocket()
    runner_ws = LoopbackWebSocket()
    server_ws.link(runner_ws)
    registry = TunnelRegistry()
    session = registry.register(runner_id, server_ws, hello)
    ws_channels: dict[str, _RunnerWSChannel] = {}
    dispatch_tasks: dict[str, asyncio.Task[None]] = {}

    async def send_server_frames() -> None:
        while True:
            data = await session.outbound_queue.get()
            if data is None:
                return
            await session.ws.send_text(data)

    async def receive_server_frames() -> None:
        while True:
            frame = decode_frame(await server_ws.receive_text())
            if isinstance(frame, (WSFrame, WSCloseFrame)):
                current = registry.get(runner_id)
                if current is not None:
                    registry.route_ws_inbound(runner_id, frame, session=current)

    async def receive_runner_frames() -> None:
        while True:
            await _handle_tunnel_frame(
                runner_app,
                await runner_ws.receive_text(),
                runner_ws.send_text,
                dispatch_tasks,
                ws_channels,
            )

    tasks = [
        asyncio.create_task(send_server_frames(), name="tunnel-send"),
        asyncio.create_task(receive_server_frames(), name="tunnel-server-receive"),
        asyncio.create_task(receive_runner_frames(), name="tunnel-runner-receive"),
    ]
    try:
        yield TunnelHarness(
            registry=registry,
            runner_id=runner_id,
            ws_channels=ws_channels,
            _server_ws=server_ws,
            _hello=hello,
            _tasks=tasks,
            _dispatch_tasks=dispatch_tasks,
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _cancel_ws_channels(ws_channels)
        for task in dispatch_tasks.values():
            task.cancel()
        await asyncio.gather(*dispatch_tasks.values(), return_exceptions=True)
        with contextlib.suppress(KeyError):
            registry.deregister(runner_id)
