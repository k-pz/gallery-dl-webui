from __future__ import annotations

import asyncio
import collections
import logging

from gallery_dl.output import Logger as GalleryDlLogger

GALLERY_DL_LOGGER_NAMES: frozenset[str] = frozenset(
    {
        "gallery-dl",
        "download",
        "postprocessor",
        "extractor",
        "archive",
        "config",
        "cache",
        "cookies",
        "formatter",
        "server",
        "aes",
        "inputfile",
        "unsupported",
        "errorfile",
    }
)


class LogHub:
    SENTINEL: object = object()

    def __init__(self, ring_size: int = 500) -> None:
        self.active_id: int | None = None
        self.ring: collections.deque[str] = collections.deque(maxlen=ring_size)
        self.subscribers: dict[int, set[asyncio.Queue[object]]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self.loop = asyncio.get_running_loop()

    def begin(self, job_id: int) -> None:
        self.active_id = job_id
        self.ring.clear()

    def end(self, job_id: int) -> None:
        if self.active_id == job_id:
            self.active_id = None
        for q in self.subscribers.get(job_id, ()):
            try:
                q.put_nowait(self.SENTINEL)
            except asyncio.QueueFull:
                pass

    def subscribe(self, job_id: int) -> asyncio.Queue[object]:
        q: asyncio.Queue[object] = asyncio.Queue(maxsize=1000)
        self.subscribers.setdefault(job_id, set()).add(q)
        if job_id == self.active_id:
            for line in self.ring:
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    break
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue[object]) -> None:
        subs = self.subscribers.get(job_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self.subscribers.pop(job_id, None)

    def _dispatch(self, line: str) -> None:
        if self.active_id is None:
            return
        self.ring.append(line)
        for q in self.subscribers.get(self.active_id, ()):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def emit_from_thread(self, line: str) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._dispatch, line)


class _HubHandler(logging.Handler):
    def __init__(self, hub: LogHub) -> None:
        super().__init__()
        self._hub = hub

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        self._hub.emit_from_thread(line)


class _GalleryDlOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name in GALLERY_DL_LOGGER_NAMES:
            return True
        return isinstance(logging.getLogger(record.name), GalleryDlLogger)


def attach_handler(hub: LogHub) -> logging.Handler:
    handler = _HubHandler(hub)
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    handler.addFilter(_GalleryDlOnlyFilter())
    logging.getLogger().addHandler(handler)
    return handler
