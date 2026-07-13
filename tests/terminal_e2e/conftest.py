"""Real tmux + runner-tunnel fixtures for T12 terminal acceptance tests."""

from __future__ import annotations

import asyncio
import shutil
import socket
import sys
import textwrap
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI

from omnigent.entities import Conversation, SessionPermission
from omnigent.inner.datamodel import TerminalEnvSpec
from omnigent.runner import create_runner_app
from omnigent.runner.transports.ws_tunnel.frames import HelloFrame
from omnigent.runner.transports.ws_tunnel.registry import RunnerSession, TunnelRegistry
from omnigent.runtime import _globals, set_runner_ws_factory
from omnigent.server._runner_ws_tunnel import _TunneledWSConn
from omnigent.server.auth import LEVEL_OWNER, LEVEL_READ, RESERVED_USER_PUBLIC, UnifiedAuthProvider
from omnigent.server.routes.terminal_attach import create_terminal_attach_router
from omnigent.terminals import TerminalRegistry
from tests.runner.helpers import NullServerClient
from tests.runner.transports.ws_tunnel.helpers import TunnelHarness, run_tunnel_harness


class _PermissionStore:
    def __init__(self) -> None:
        self.grants: dict[tuple[str, str], SessionPermission] = {}

    def add(self, user_id: str, session_id: str, level: int) -> None:
        self.grants[(user_id, session_id)] = SessionPermission(
            user_id=user_id, conversation_id=session_id, level=level
        )

    def get(self, user_id: str, conversation_id: str) -> SessionPermission | None:
        return self.grants.get((user_id, conversation_id))

    def is_admin(self, user_id: str) -> bool:
        return False

    def check_access(self, user_id: str | None, conversation_id: str, required_level: int) -> bool:
        if user_id is None:
            return False
        grant = self.get(user_id, conversation_id) or self.get(
            RESERVED_USER_PUBLIC, conversation_id
        )
        return grant is not None and grant.level >= required_level

    def get_permission_level(self, user_id: str | None, conversation_id: str) -> int | None:
        if user_id is None:
            return None
        grant = self.get(user_id, conversation_id) or self.get(
            RESERVED_USER_PUBLIC, conversation_id
        )
        return grant.level if grant is not None else None


class _ConversationStore:
    def __init__(self, session_id: str) -> None:
        self.conversation = Conversation(
            id=session_id,
            created_at=0,
            updated_at=0,
            root_conversation_id=session_id,
        )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.conversation if conversation_id == self.conversation.id else None


@dataclass
class TerminalTunnelFixture:
    """Handles exposed by one real tmux terminal behind a runner tunnel."""

    session_id: str
    terminal_id: str
    websocket_base_url: str
    runner_id: str
    tunnel_registry: TunnelRegistry
    terminal_registry: TerminalRegistry
    tunnel: TunnelHarness

    def url(
        self,
        *,
        read_only: bool = False,
        transport: str = "control",
    ) -> str:
        """Return the public browser-facing terminal attach URL."""
        return (
            f"{self.websocket_base_url}/v1/sessions/{self.session_id}/resources/terminals/"
            f"{self.terminal_id}/attach?read_only={'true' if read_only else 'false'}"
            f"&transport={transport}"
        )

    async def disconnect_runner(self) -> RunnerSession:
        """Drop the active runner generation while leaving tmux alive."""
        return await self.tunnel.disconnect()

    def reconnect_runner(self) -> None:
        """Register a new tunnel generation for the same runner and tmux pane."""
        assert self.tunnel_registry.get(self.runner_id) is None
        self.tunnel.reconnect()

    async def close_terminal(self) -> None:
        """Kill only the tmux terminal while leaving the runner online."""
        closed = await self.terminal_registry.close(self.session_id, "probe", "main")
        assert closed


@pytest_asyncio.fixture
async def terminal_tunnel(tmp_path: Path) -> AsyncIterator[TerminalTunnelFixture]:
    """Launch a deterministic terminal and expose it over the real tunnel stack."""
    if shutil.which("tmux") is None:
        pytest.fail("T12 requires tmux; install it in the supported test environment")

    session_id = "conv_t12_control"
    terminal_id = "terminal_probe_main"
    terminal_registry = TerminalRegistry()
    script = textwrap.dedent(
        """
        import os
        import signal
        import sys

        def report_size(*_args):
            size = os.get_terminal_size(sys.stdout.fileno())
            print(f"T12_SIZE:{size.columns}x{size.lines}", flush=True)

        signal.signal(signal.SIGWINCH, report_size)
        print("T12_READY", flush=True)
        for line in sys.stdin:
            sys.stdout.write("T12_ECHO:" + line)
            sys.stdout.flush()
        """
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

    runner_id = "runner-t12-control"
    hello = HelloFrame(
        runner_version="t12-test",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["caller_process"],
        terminal_transports=["control", "pty"],
    )
    permission_store = _PermissionStore()
    permission_store.add("owner@example.com", session_id, LEVEL_OWNER)
    permission_store.add("viewer@example.com", session_id, LEVEL_READ)
    conversation_store = _ConversationStore(session_id)

    async with run_tunnel_harness(runner_app, runner_id=runner_id, hello=hello) as tunnel:

        def connect_runner(runner_path: str) -> _TunneledWSConn:
            session = tunnel.registry.get(runner_id)
            if session is None:
                raise RuntimeError("runner is offline")
            return _TunneledWSConn(
                registry=tunnel.registry,
                session=session,
                runner_path=runner_path,
            )

        prior_factory = _globals._runner_ws_factory
        set_runner_ws_factory(connect_runner)
        server_app = FastAPI()
        server_app.include_router(
            create_terminal_attach_router(
                auth_provider=UnifiedAuthProvider(source="header"),
                permission_store=permission_store,  # type: ignore[arg-type]
                conversation_store=conversation_store,  # type: ignore[arg-type]
            ),
            prefix="/v1",
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(server_app, log_level="warning", lifespan="off"))
        server_task = asyncio.create_task(
            server.serve(sockets=[sock]), name="t12-public-attach-server"
        )
        try:
            while not server.started:
                await asyncio.sleep(0.01)
            yield TerminalTunnelFixture(
                session_id=session_id,
                terminal_id=terminal_id,
                websocket_base_url=f"ws://127.0.0.1:{port}",
                runner_id=runner_id,
                tunnel_registry=tunnel.registry,
                terminal_registry=terminal_registry,
                tunnel=tunnel,
            )
        finally:
            server.should_exit = True
            await server_task
            set_runner_ws_factory(prior_factory)
            sock.close()
            await terminal_registry.shutdown()
