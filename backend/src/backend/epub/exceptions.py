from __future__ import annotations

from backend.exceptions import ConflictError, NotFoundError, WebUIError


class EpubBookNotFound(NotFoundError):
    detail = "EPUB book not found"


class EpubBookEmpty(ConflictError):
    detail = "no packed chapters on disk fall in this book's range"


class EpubExportBusy(ConflictError):
    detail = "an EPUB export for this series is already running"


class EpubFileMissing(NotFoundError):
    detail = "this book has not been exported yet (or its file was removed)"


class EpubExportFailed(WebUIError):
    status_code = 500
    detail = "EPUB export failed"
