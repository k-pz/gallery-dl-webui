"""In-process pub/sub for state changes that the websocket layer rebroadcasts.

The event bus is intentionally minimal: a synchronous `publish(event)` call drops
the payload into every subscriber's bounded queue. Subscribers consume via
`subscribe()` which returns a `Subscription` async context manager handing back
an `asyncio.Queue`. If a slow consumer fills its queue, the oldest event is
dropped — keeping the bus non-blocking so background workers never stall on a
disconnected websocket client.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# When set (by `RequestEventCollectorMiddleware`), every `EventBus.publish`
# also appends to this list. The middleware then drains the list into the
# `X-Events` response header so the mutating client invalidates its TanStack
# caches without waiting for the websocket roundtrip. None outside a
# request — worker / poller publishes still only fan-out to WS subscribers.
_request_events: ContextVar[list[Event] | None] = ContextVar("_request_events", default=None)


@dataclass(frozen=True)
class Event:
    """Topic-tagged payload pushed onto the bus.

    `topic` is a coarse channel name (`downloads`, `targets`, `config`,
    `maintenance`, `progress`); `type` is the specific action (`updated`,
    `deleted`, `chapter`, …); `data` is the JSON-serialisable body.
    """

    topic: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"topic": self.topic, "type": self.type, "data": self.data}


def open_request_event_buffer() -> tuple[list[Event], Token[list[Event] | None]]:
    """Start collecting events for the duration of this contextvar scope.

    Returns the list `EventBus.publish` will append to plus the contextvar
    token the caller must hand back to `close_request_event_buffer`. Nested
    calls work: the inner buffer wins while open, and resetting via the token
    restores the outer one instead of blanking it.
    """
    buf: list[Event] = []
    token = _request_events.set(buf)
    return buf, token


def close_request_event_buffer(token: Token[list[Event] | None]) -> None:
    _request_events.reset(token)


class EventBus:
    DEFAULT_QUEUE_SIZE = 256

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = asyncio.Lock()

    def publish(self, event: Event) -> None:
        """Fan-out an event to every subscriber.

        Drops the oldest item if a subscriber's queue is full — the bus is
        meant to be non-blocking, and a missed transient event is better than
        a stalled worker. Workers publishing from threads should use
        `publish_threadsafe`.

        If a request-scoped buffer is open (`open_request_event_buffer`), the
        event is also appended there so the middleware can emit it in the
        response's `X-Events` header.
        """
        buf = _request_events.get()
        if buf is not None:
            buf.append(event)
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("event bus queue full, dropping event %s/%s", event.topic, event.type)

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, event: Event) -> None:
        """Publish from a non-event-loop thread (e.g. gallery-dl callbacks).

        Schedules `publish` onto the loop via `call_soon_threadsafe`, which is
        the documented way to interact with asyncio primitives from another
        thread.
        """
        try:
            loop.call_soon_threadsafe(self.publish, event)
        except RuntimeError:
            # Loop is closing — nothing useful to do, swallow.
            pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subscribers.discard(q)


# Convenience constructors used by the publishers below — keeping the topic /
# type strings in one place makes the protocol easier to audit.


def downloads_event(action: str, **data: Any) -> Event:
    return Event(topic="downloads", type=action, data=data)


def targets_event(action: str, **data: Any) -> Event:
    return Event(topic="targets", type=action, data=data)


def config_event(**data: Any) -> Event:
    return Event(topic="config", type="updated", data=data)


def maintenance_event(action: str, **data: Any) -> Event:
    return Event(topic="maintenance", type=action, data=data)


def progress_event(download_id: int, **data: Any) -> Event:
    """Per-download fine-grained progress (file completed, postprocess tick)."""
    return Event(topic="progress", type="download", data={"download_id": download_id, **data})


def maintenance_progress_event(job_id: int, **data: Any) -> Event:
    return Event(topic="progress", type="maintenance", data={"job_id": job_id, **data})
