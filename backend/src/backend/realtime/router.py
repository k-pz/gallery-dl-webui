"""WebSocket endpoint that streams `EventBus` payloads to subscribed clients.

The protocol is one-way (server → client) JSON: each frame is one event
`{topic, type, data}`. Clients connect, optionally request a snapshot, then
react to incoming messages by invalidating cached state.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.events import Event, EventBus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def events_stream(ws: WebSocket) -> None:
    bus: EventBus = ws.app.state.event_bus
    await ws.accept()
    # Tell the client the channel is live — they can decide whether to fetch a
    # fresh snapshot of state or wait for the next event.
    try:
        await ws.send_json(Event(topic="system", type="connected").to_json())
    except WebSocketDisconnect, RuntimeError:
        return

    async with bus.subscribe() as queue:
        receive_task = asyncio.create_task(_drain_incoming(ws), name="ws-drain")
        try:
            while True:
                if receive_task.done():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # Keep-alive ping so intermediaries (reverse proxies) don't
                    # close the idle socket.
                    try:
                        await ws.send_json(Event(topic="system", type="ping").to_json())
                    except WebSocketDisconnect, RuntimeError:
                        break
                    continue
                try:
                    await ws.send_json(event.to_json())
                except WebSocketDisconnect, RuntimeError:
                    break
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError, Exception:
                pass


async def _drain_incoming(ws: WebSocket) -> None:
    """Keep the receive loop alive — we don't accept commands but the protocol
    still requires draining the inbound side so a client-initiated close is
    detected promptly."""
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        return
    except Exception:
        return
