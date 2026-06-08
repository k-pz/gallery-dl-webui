"""Per-chapter failure-reason capture for gallery-dl runs.

A `ChapterErrorCollector` is a logging.Handler attached to the root logger
around `job.run()`. gallery-dl extractor loggers (e.g. `mangadex`) propagate to
root. The collector only banks WARNING+ records emitted on the worker thread
(filtered by `record.thread`) while a chapter context is set, so it never picks
up the event loop's own logging. The download worker is strictly serial, so a
process-global handler only ever serves one job at a time.
"""

from __future__ import annotations

import logging


class ChapterErrorCollector(logging.Handler):
    def __init__(self, chapter_ctx: list[str], thread_id: int) -> None:
        super().__init__(level=logging.WARNING)
        self._ctx = chapter_ctx
        self._thread_id = thread_id
        self.errors: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_id:
            return
        chapter = self._ctx[0] if self._ctx else ""
        if not chapter:
            return
        # Keep the first (usually root-cause) error per chapter.
        self.errors.setdefault(chapter, record.getMessage())
