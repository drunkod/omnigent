"""Real tmux + runner-tunnel fixtures for T12 terminal acceptance tests."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from omnigent.inner.datamodel import TerminalEnvSpec
from omnigent.runner import create_runner_app
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
from omnigent.server._runner_ws_tunnel import _TunneledWSConn
from omnigent.terminals import TerminalRegistry
from tests.runner.helpers import NullServerClient


class _LoopbackWebSocket:
    """One half of an in-memory runner tunnel WebSocket pair."""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[str] = asyncio.Queue()
        self.peer: _LoopbackWebSocket | None = None

    def link(self, peer: _LoopbackWebSocket) -> None:
        self.peer = peer
        peer.peer = self

    async def send_text(self, data: str) -> None:
        assert self.peer is not None
        await self.peer.inbound.put(data)

    async def receive_text(self) -> str:
        return await self.inbound.get()


@dataclass
class TerminalTunnelFixture:
    """Handles exposed by one real tmux terminal behind a runner tunnel."""

    registry: TunnelRegistry
    runner_id: str
    session_id: str
    terminal_id: str

    def connect(
        self,
        *,
        read_only: bool = False,
        transport: str = "control",
    ) -> _TunneledWSConn:
        """Open the server-side connection used by the terminal attach proxy."""
        session = self.registry.get(self.runner_id)
        assert session is not None
        runner_path = (
            f"/v1/sessions/{self.session_id}/resources/terminals/"
            f"{self.terminal_id}/attach?read_only={'true' if read_only else 'false'}"
            f"&transport={transport}"
        )
        return _TunneledWSConn(
            registry=self.registry,
            session=session,
            runner_path=runner_path,
        )


@pytest_asyncio.fixture
async def terminal_tunnel(tmp_path: Path) -> AsyncIterator[TerminalTunnelFixture]:
    """Launch a deterministic terminal and expose it over the real tunnel stack."""
    if shutil.which("tmux") is None:
        pytest.fail("T12 requires tmux; install it in the supported test environment")

    session_id = "conv_t12_control"
    terminal_id = "terminal_probe_main"
    terminal_registry = TerminalRegistry()
    script = (
        "import sys; "
        "print('T12_READY', flush=True); "
        "[(sys.stdout.write('T12_ECHO:' + line), sys.stdout.flush()) for line in sys.stdin]"
    )
    await terminal_registry.launch(
        session_id,
        "probe",
        "main",
        TerminalEnvSpec(
            command=sys.executable,
            args=["-u", "-c", script],
            terminal_transport="control",
        ),
    )
    runner_app = create_runner_app(  # type: ignore[arg-type]
        server_client=NullServerClient(),
        terminal_registry=terminal_registry,
        runner_workspace=tmp_path,
        per_session_workspace=False,
    )

    server_ws = _LoopbackWebSocket()
    runner_ws = _LoopbackWebSocket()
    server_ws.link(runner_ws)
    tunnel_registry = TunnelRegistry()
    runner_id = "runner-t12-control"
    session = tunnel_registry.register(
        runner_id,
        server_ws,
        HelloFrame(
            runner_version="t12-test",
            frame_protocol_version=1,
            harnesses=["test"],
            envs=["caller_process"],
            terminal_transports=["control", "pty"],
        ),
    )
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
                tunnel_registry.route_ws_inbound(runner_id, frame, session=session)

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
        asyncio.create_task(send_server_frames(), name="t12-tunnel-send"),
        asyncio.create_task(receive_server_frames(), name="t12-server-receive"),
        asyncio.create_task(receive_runner_frames(), name="t12-runner-receive"),
    ]
    try:
        yield TerminalTunnelFixture(
            registry=tunnel_registry,
            runner_id=runner_id,
            session_id=session_id,
            terminal_id=terminal_id,
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
            tunnel_registry.deregister(runner_id)
        await terminal_registry.shutdown()
