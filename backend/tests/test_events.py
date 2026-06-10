"""Tests for the in-process event bus and the request-scoped event buffer."""

import asyncio

from backend.events import (
    EventBus,
    close_request_event_buffer,
    downloads_event,
    open_request_event_buffer,
)


async def test_subscribe_receives_published_events() -> None:
    bus = EventBus()
    async with bus.subscribe() as q:
        bus.publish(downloads_event("updated", id=1))
        event = await asyncio.wait_for(q.get(), timeout=1)
    assert event.topic == "downloads"
    assert event.data == {"id": 1}


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    async with bus.subscribe() as q:
        pass
    bus.publish(downloads_event("updated", id=1))
    assert q.empty()


async def test_full_queue_drops_oldest_event() -> None:
    bus = EventBus(queue_size=2)
    async with bus.subscribe() as q:
        for i in range(3):
            bus.publish(downloads_event("updated", id=i))
        # Oldest (id=0) was dropped to make room; 1 and 2 survive in order.
        assert (await q.get()).data == {"id": 1}
        assert (await q.get()).data == {"id": 2}
        assert q.empty()


async def test_publish_threadsafe_lands_on_the_loop() -> None:
    bus = EventBus()
    loop = asyncio.get_running_loop()
    async with bus.subscribe() as q:
        await asyncio.to_thread(bus.publish_threadsafe, loop, downloads_event("updated", id=7))
        event = await asyncio.wait_for(q.get(), timeout=1)
    assert event.data == {"id": 7}


async def test_request_buffer_collects_and_nests() -> None:
    bus = EventBus()
    outer, outer_token = open_request_event_buffer()
    bus.publish(downloads_event("updated", id=1))

    inner, inner_token = open_request_event_buffer()
    bus.publish(downloads_event("updated", id=2))
    close_request_event_buffer(inner_token)

    # Closing the inner buffer restores the outer one instead of blanking
    # the contextvar — events keep landing in the outer scope.
    bus.publish(downloads_event("updated", id=3))
    close_request_event_buffer(outer_token)
    bus.publish(downloads_event("updated", id=4))

    assert [e.data["id"] for e in outer] == [1, 3]
    assert [e.data["id"] for e in inner] == [2]
