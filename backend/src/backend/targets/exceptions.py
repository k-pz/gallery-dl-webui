from __future__ import annotations

from backend.exceptions import ConflictError, NotFoundError


class TargetNotFound(NotFoundError):
    detail = "target not found"


class TargetHasActiveDownload(ConflictError):
    detail = "target already has an active download — wait for it to finish"


class TargetHasActiveDownloadOnDelete(ConflictError):
    detail = "target has an active download — cancel it first"
