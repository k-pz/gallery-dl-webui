"""Per-job, in-memory progress + log tail for maintenance jobs.

Mirrors the design of `downloads.live_progress.LiveProgress`: a single writer
(the maintenance worker thread) and many readers (the progress endpoint).
List append + int reassignment are atomic under the GIL, so a snapshot can be
taken without locking. State is dropped from memory once a job reaches a
terminal status — terminal-state callers read the persisted row instead.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class MaintenanceProgressSnapshot:
    total: int
    done: int
    lines: list[str]


class MaintenanceLiveProgress:
    DEFAULT_TAIL_SIZE = 200

    def __init__(self, *, tail_size: int = DEFAULT_TAIL_SIZE) -> None:
        self._tail_size = tail_size
        self._lines: dict[int, deque[str]] = {}
        self._total: dict[int, int] = {}
        self._done: dict[int, int] = {}

    def start(self, job_id: int) -> None:
        self._lines[job_id] = deque(maxlen=self._tail_size)
        self._total[job_id] = 0
        self._done[job_id] = 0

    def set_total(self, job_id: int, total: int) -> None:
        if job_id in self._total:
            self._total[job_id] = total

    def increment_done(self, job_id: int) -> None:
        if job_id in self._done:
            self._done[job_id] += 1

    def record(self, job_id: int, line: str) -> None:
        bucket = self._lines.get(job_id)
        if bucket is not None:
            bucket.append(line)

    def snapshot(self, job_id: int) -> MaintenanceProgressSnapshot | None:
        bucket = self._lines.get(job_id)
        if bucket is None:
            return None
        return MaintenanceProgressSnapshot(
            total=self._total.get(job_id, 0),
            done=self._done.get(job_id, 0),
            lines=list(bucket),
        )

    def clear(self, job_id: int) -> None:
        self._lines.pop(job_id, None)
        self._total.pop(job_id, None)
        self._done.pop(job_id, None)
