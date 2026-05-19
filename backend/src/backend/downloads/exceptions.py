from __future__ import annotations

from backend.exceptions import ConflictError, NotFoundError, WebUIError


class DownloadNotFound(NotFoundError):
    detail = "download not found"


class DownloadAlreadyTerminal(ConflictError):
    def __init__(self, status: str) -> None:
        super().__init__(f"download already in terminal state: {status}")


class DownloadNotTerminal(ConflictError):
    def __init__(self, status: str) -> None:
        super().__init__(f"can only requeue terminal jobs (current: {status})")


class DownloadVanished(WebUIError):
    """Raised when a row we just mutated has disappeared on us."""

    status_code = 500

    def __init__(self, download_id: int) -> None:
        super().__init__(f"download {download_id} disappeared")
