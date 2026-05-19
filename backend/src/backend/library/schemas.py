from __future__ import annotations

from pydantic import BaseModel


class LibraryImportResult(BaseModel):
    imported: int
    updated: int
    errors: list[str]
