"""Small asyncio helpers shared by the background workers."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def log_task_death(task: asyncio.Task[None]) -> None:
    """Done-callback that makes an unexpected background-task exit loud.

    The worker loops are written to never raise, so any exception landing
    here is a bug — but a silently vanished queue is far worse than a noisy
    one, so surface the death in the logs instead of relying on asyncio's
    unretrieved-exception warning at GC time.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background task %r died: %r", task.get_name(), exc)
