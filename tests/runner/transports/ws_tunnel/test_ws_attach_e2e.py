"""End-to-end test for tunneled WebSocket attach over the runner tunnel.

Wires up: server-side ``_TunneledWSConn`` factory + tunnel registry +
``_handle_tunnel_frame`` on the runner side + a runner-side FastAPI app
whose ``@app.websocket(...)`` route echoes frames. Verifies that bytes
and text round-trip in both directions and that a runner-side close is
surfaced as :class:`websockets.exceptions.ConnectionClosed` with the
peer-supplied code+reason on ``.rcvd`` (the shape the
terminal-attach shuttle expects).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pytest
from fastapi import FastAPI, WebSocket
from websockets.exceptions import ConnectionClosed

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runner.transports.ws_tunnel.frames import (
    HelloFrame,
    WSCloseFrame,
    WSFrame,
    WSOpenFrame,
    decode_frame,
    encode_frame,
)
from omnigent.runner.transports.ws_tunnel.registry import TunnelRegistry
from omnigent.server._runner_ws_tunnel import _TunneledWSConn
from tests.runner.transports.ws_tunnel.helpers import LoopbackWebSocket, run_tunnel_harness


def _build_echo_app() -> FastAPI:
    app = FastAPI()

    @app.websocket("/v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach")
    async def attach(websocket: WebSocket, session_id: str, terminal_id: str) -> None:
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("text") == "close-me":
                    # Surface a custom close code+reason so the test can
                    # assert ConnectionClosed.rcvd round-trips.
                    await websocket.close(code=4242, reason="goodbye")
                    return
                if msg.get("text") is not None:
                    await websocket.send_text(f"echo:{msg['text']}")
                elif msg.get("bytes") is not None:
                    await websocket.send_bytes(b"binary-echo:" + msg["bytes"])
        except Exception:
            return

    return app


@pytest.mark.asyncio
async def test_text_and_binary_round_trip_over_tunneled_ws_attach() -> None:
    """Text and binary frames round-trip in both directions."""
    runner_app = _build_echo_app()
    hello = HelloFrame(
        runner_version="0.1.0-test",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["test"],
    )
    runner_id = "runner-attach-1"
    async with run_tunnel_harness(runner_app, runner_id=runner_id, hello=hello) as tunnel:
        session = tunnel.registry.get(runner_id)
        assert session is not None
        # Server side: open a tunneled WS attach via the factory's
        # connection class directly.
        runner_path = (
            "/v1/sessions/conv_x/resources/terminals/terminal_bash_s1/attach?read_only=false"
        )
        async with _TunneledWSConn(
            registry=tunnel.registry,
            session=session,
            runner_path=runner_path,
        ) as conn:
            # Wait until the runner dispatch task has accepted, so the
            # echo route's receive loop is in place before we send.
            for _ in range(20):
                if tunnel.ws_channels and any(ch.accepted for ch in tunnel.ws_channels.values()):
                    break
                await asyncio.sleep(0.01)

            # Text → text round-trip.
            await conn.send("hello")
            reply = await asyncio.wait_for(conn.recv(), timeout=2.0)
            assert reply == "echo:hello"

            # Binary → binary round-trip.
            await conn.send(b"\x00\x01\x02ABC")
            reply2 = await asyncio.wait_for(conn.recv(), timeout=2.0)
            assert reply2 == b"binary-echo:\x00\x01\x02ABC"


@pytest.mark.asyncio
async def test_runner_side_close_surfaces_as_connection_closed_with_code() -> None:
    """A runner-initiated WS close arrives on the server as ConnectionClosed."""
    runner_app = _build_echo_app()
    hello = HelloFrame(
        runner_version="0.1.0-test",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["test"],
    )
    runner_id = "runner-attach-2"
    async with run_tunnel_harness(runner_app, runner_id=runner_id, hello=hello) as tunnel:
        session = tunnel.registry.get(runner_id)
        assert session is not None
        runner_path = (
            "/v1/sessions/conv_y/resources/terminals/terminal_bash_s1/attach?read_only=false"
        )
        async with _TunneledWSConn(
            registry=tunnel.registry,
            session=session,
            runner_path=runner_path,
        ) as conn:
            for _ in range(20):
                if tunnel.ws_channels and any(ch.accepted for ch in tunnel.ws_channels.values()):
                    break
                await asyncio.sleep(0.01)

            await conn.send("close-me")
            with pytest.raises(ConnectionClosed) as exc_info:
                await asyncio.wait_for(conn.recv(), timeout=2.0)
            assert exc_info.value.rcvd is not None
            assert exc_info.value.rcvd.code == 4242
            assert exc_info.value.rcvd.reason == "goodbye"


@pytest.mark.asyncio
async def test_valid_unadvertised_transport_is_rejected_before_channel_allocation() -> None:
    """A canonical transport absent from a non-empty hello list fails closed."""
    registry = TunnelRegistry()
    ws, peer = LoopbackWebSocket(), LoopbackWebSocket()
    ws.link(peer)
    hello = HelloFrame(
        runner_version="0.1.0",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["test"],
        terminal_transports=["control"],
    )
    session = registry.register("runner-capability", ws, hello)
    conn = _TunneledWSConn(
        registry=registry,
        session=session,
        runner_path=(
            "/v1/sessions/conv/resources/terminals/terminal_x/attach?transport=pty"
        ),
    )

    with pytest.raises(OmnigentError) as exc_info:
        await conn.__aenter__()

    assert exc_info.value.code == ErrorCode.TERMINAL_TRANSPORT_UNSUPPORTED
    assert session.ws_channels == {}
    registry.deregister(session.runner_id, session=session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("advertised", "query"),
    [
        ([], "transport=pty"),
        (["control"], "transport=not-a-real-transport"),
    ],
)
async def test_legacy_or_invalid_transport_query_remains_permissive(
    advertised: list[str],
    query: str,
) -> None:
    """Rolling upgrades and stray query values preserve the normal attach path."""
    registry = TunnelRegistry()
    ws, peer = LoopbackWebSocket(), LoopbackWebSocket()
    ws.link(peer)
    hello = HelloFrame(
        runner_version="0.1.0",
        frame_protocol_version=1,
        harnesses=["test"],
        envs=["test"],
        terminal_transports=advertised,
    )
    session = registry.register("runner-compatible", ws, hello)
    conn = _TunneledWSConn(
        registry=registry,
        session=session,
        runner_path=f"/v1/sessions/conv/resources/terminals/terminal_x/attach?{query}",
    )

    await conn.__aenter__()
    try:
        assert len(session.ws_channels) == 1
    finally:
        await conn.__aexit__(None, None, None)
        registry.deregister(session.runner_id, session=session)


@pytest.mark.asyncio
async def test_frame_encode_decode_round_trip() -> None:
    """The three new frame kinds survive encode/decode."""
    for frame in (
        WSOpenFrame(ch_id="ab12", path="/v1/x", query_string="a=b"),
        WSFrame(ch_id="ab12", data="hello", encoding="utf-8"),
        WSFrame(
            ch_id="ab12",
            data=base64.b64encode(b"\x00\xff").decode("ascii"),
            encoding="base64",
        ),
        WSCloseFrame(ch_id="ab12", code=4242, reason="bye"),
    ):
        round_tripped = decode_frame(encode_frame(frame))
        assert round_tripped == frame


@pytest.mark.asyncio
async def test_open_ws_channel_session_guard_rejects_stale_session() -> None:
    """open_ws_channel raises KeyError when its session has been replaced."""
    registry = TunnelRegistry()
    ws_a, peer_a = LoopbackWebSocket(), LoopbackWebSocket()
    ws_a.link(peer_a)
    hello = HelloFrame(
        runner_version="0.1.0",
        frame_protocol_version=1,
        harnesses=["t"],
        envs=["t"],
    )
    session_old = registry.register("runner-replace", ws_a, hello)
    # New session replaces the old one.
    ws_b, peer_b = LoopbackWebSocket(), LoopbackWebSocket()
    ws_b.link(peer_b)
    registry.register("runner-replace", ws_b, hello)
    with pytest.raises(KeyError):
        registry.open_ws_channel("runner-replace", "stale01", session=session_old)
    with contextlib.suppress(KeyError):
        registry.deregister("runner-replace")
