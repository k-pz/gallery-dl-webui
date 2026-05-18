class LiveProgress:
    """Per-download in-memory record of completed file relpaths.

    Single writer (the worker thread running gallery-dl) and many readers (the
    progress endpoint). List append is atomic under the GIL; snapshot() returns
    a copy so readers can iterate without locks.
    """

    def __init__(self) -> None:
        self._completed: dict[int, list[str]] = {}

    def start(self, download_id: int) -> None:
        self._completed[download_id] = []

    def record(self, download_id: int, relpath: str) -> None:
        bucket = self._completed.get(download_id)
        if bucket is not None:
            bucket.append(relpath)

    def snapshot(self, download_id: int) -> list[str] | None:
        bucket = self._completed.get(download_id)
        return list(bucket) if bucket is not None else None

    def clear(self, download_id: int) -> None:
        self._completed.pop(download_id, None)
