"""Real tmux + runner-tunnel fixtures for T12 terminal acceptance tests."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
import tempfile
import textwrap
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI

import omnigent.inner.terminal as terminal_mod
from omnigent.entities import Conversation, SessionPermission
from omnigent.inner.datamodel import TerminalEnvSpec
from omnigent.runner import create_runner_app
from omnigent.runner.transports.ws_tunnel.frames import HelloFrame
from omnigent.runner.transports.ws_tunnel.registry import RunnerSession, TunnelRegistry
from omnigent.runtime import _globals, set_runner_ws_factory
from omnigent.server._runner_ws_tunnel import _TunneledWSConn
from omnigent.server.auth import (
    LEVEL_OWNER,
    LEVEL_READ,
    RESERVED_USER_PUBLIC,
    UnifiedAuthProvider,
)
from omnigent.server.routes.terminal_attach import create_terminal_attach_router
from omnigent.terminals import TerminalRegistry
from tests.runner.helpers import NullServerClient
from tests.runner.transports.ws_tunnel.helpers import (
    TunnelHarness,
    run_tunnel_harness,
)

# macOS sockaddr_un.sun_path is 104 bytes including the terminating NUL.
# Keep generated tmux socket pathnames below 104 encoded filesystem bytes.
_MACOS_UNIX_SOCKET_PATH_MAX_BYTES = 104

# Intentionally short: the production layer adds another
# "omnigent-terminal-<random>/tmux.sock" beneath this directory.
_TMUX_TEST_TEMP_PREFIX = "ogt-"

# CPython's tempfile candidate names use eight characters in the Python
# versions supported by this repository. The real-path regression below still
# creates a directory through tempfile.mkdtemp, so a future change cannot pass
# silently merely because this validation model becomes stale.
_TEMPFILE_RANDOM_SUFFIX = "12345678"


def _short_writable_temp_base() -> Path:
    """Return a short writable base for tmux Unix-domain sockets."""
    candidates: list[Path] = []

    if os.name == "posix":
        candidates.append(Path("/tmp"))

    configured_temp = Path(tempfile.gettempdir())
    if configured_temp not in candidates:
        candidates.append(configured_temp)

    for candidate in candidates:
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
            return candidate

    raise RuntimeError(
        "terminal E2E tests require a writable temporary directory for private tmux sockets"
    )


def _validate_tmux_socket_path(root: Path) -> None:
    """Verify a production-shaped tmux socket fits the macOS limit."""
    private_dir_name = f"{terminal_mod._TERMINAL_DIR_PREFIX}{_TEMPFILE_RANDOM_SUFFIX}"
    socket_path = root.resolve() / private_dir_name / "tmux.sock"
    encoded_path = os.fsencode(socket_path)

    if len(encoded_path) >= _MACOS_UNIX_SOCKET_PATH_MAX_BYTES:
        raise RuntimeError(
            "terminal E2E tmux socket path exceeds the macOS limit: "
            f"{len(encoded_path)} bytes: {socket_path}"
        )


@pytest.fixture
def _tmux_temp_root(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Force production terminal paths beneath a short fixture root.

    Both Python's default temporary-directory state and Omnigent's explicit
    terminal-root resolver are patched. The latter is required because
    production passes ``dir=_terminals_tmp_root()`` to ``tempfile.mkdtemp``.
    """
    base = _short_writable_temp_base()
    root = Path(
        tempfile.mkdtemp(
            prefix=_TMUX_TEST_TEMP_PREFIX,
            dir=str(base),
        )
    )

    _validate_tmux_socket_path(root)

    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setenv("TEMP", str(root))
    monkeypatch.setenv("TMP", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))

    # This is the path actually consulted by create_terminal_instance().
    monkeypatch.setattr(
        terminal_mod,
        "_terminals_tmp_root",
        lambda: root,
    )

    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


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


_UVICORN_START_TIMEOUT_SECONDS = 10.0
_UVICORN_STOP_TIMEOUT_SECONDS = 5.0


async def _wait_for_uvicorn_start(
    server: uvicorn.Server,
    server_task: asyncio.Task[None],
) -> None:
    """Wait for Uvicorn to start or propagate an early server failure."""
    while not server.started:
        if server_task.done():
            await server_task
            raise RuntimeError("terminal E2E attach server exited before reporting startup")

        await asyncio.sleep(0.01)


@pytest_asyncio.fixture
async def terminal_tunnel(
    tmp_path: Path,
    _tmux_temp_root: Path,
) -> AsyncIterator[TerminalTunnelFixture]:
    """Launch a deterministic terminal and expose it over the real tunnel stack."""
    if shutil.which("tmux") is None:
        pytest.fail("T12 requires tmux; install it in the supported test environment")

    session_id = "conv_t12_control"
    terminal_id = "terminal_probe_main"
    terminal_registry = TerminalRegistry()

    try:
        script = textwrap.dedent(
            r"""
            import os
            import signal
            import sys
            import termios
            import tty

            def report_size(*_args):
                size = os.get_terminal_size(sys.stdout.fileno())
                print(f"T12_SIZE:{size.columns}x{size.lines}", flush=True)

            def report_raw_bytes():
                fd = sys.stdin.fileno()
                previous = termios.tcgetattr(fd)
                payload = bytearray()
                try:
                    tty.setraw(fd)
                    print("T12_RAW_READY", flush=True)
                    while b"\x04" not in payload:
                        payload.extend(os.read(fd, 64))
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, previous)
                raw = bytes(payload).split(b"\x04", 1)[0]
                print("T12_RAW_HEX:" + raw.hex(), flush=True)

            signal.signal(signal.SIGWINCH, report_size)
            print("T12_READY", flush=True)

            for line in sys.stdin:
                command = line.rstrip("\r\n")

                if command == "T12_RAW":
                    report_raw_bytes()
                elif command == "T12_ALTSCREEN":
                    sys.stdout.write(
                        "\x1b[?1049hT12_ALT_ENTER"
                        "\x1b[?1049lT12_ALT_EXIT\n"
                    )
                    sys.stdout.flush()
                elif command == "T12_BURST":
                    for index in range(256):
                        print(
                            f"T12_BURST:{index:04d}:" + "x" * 128,
                            flush=True,
                        )
                else:
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
        permission_store.add(
            "owner@example.com",
            session_id,
            LEVEL_OWNER,
        )
        permission_store.add(
            "viewer@example.com",
            session_id,
            LEVEL_READ,
        )
        conversation_store = _ConversationStore(session_id)

        async with run_tunnel_harness(
            runner_app,
            runner_id=runner_id,
            hello=hello,
        ) as tunnel:

            def connect_runner(
                runner_path: str,
            ) -> _TunneledWSConn:
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

            sock: socket.socket | None = None
            server: uvicorn.Server | None = None
            server_task: asyncio.Task[None] | None = None

            try:
                server_app = FastAPI()
                server_app.include_router(
                    create_terminal_attach_router(
                        auth_provider=UnifiedAuthProvider(source="header"),
                        permission_store=permission_store,  # type: ignore[arg-type]
                        conversation_store=conversation_store,  # type: ignore[arg-type]
                    ),
                    prefix="/v1",
                )

                sock = socket.socket(
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                )
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_REUSEADDR,
                    1,
                )
                sock.bind(("127.0.0.1", 0))
                sock.listen()

                port = sock.getsockname()[1]
                server = uvicorn.Server(
                    uvicorn.Config(
                        server_app,
                        log_level="warning",
                        lifespan="off",
                    )
                )
                server_task = asyncio.create_task(
                    server.serve(sockets=[sock]),
                    name="t12-public-attach-server",
                )

                await asyncio.wait_for(
                    _wait_for_uvicorn_start(
                        server,
                        server_task,
                    ),
                    timeout=_UVICORN_START_TIMEOUT_SECONDS,
                )

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
                if server is not None:
                    server.should_exit = True

                try:
                    if server_task is not None:
                        try:
                            await asyncio.wait_for(
                                server_task,
                                timeout=_UVICORN_STOP_TIMEOUT_SECONDS,
                            )
                        except TimeoutError:
                            server_task.cancel()
                            await asyncio.gather(
                                server_task,
                                return_exceptions=True,
                            )
                finally:
                    set_runner_ws_factory(prior_factory)

                    if sock is not None:
                        sock.close()
    finally:
        # This executes even when launch, tunnel setup, socket binding,
        # or Uvicorn startup fails before the fixture yields.
        await terminal_registry.shutdown()
