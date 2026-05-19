from __future__ import annotations

from pydantic import BaseModel


class DirEntry(BaseModel):
    path: str
    name: str
    depth: int


class DirCreate(BaseModel):
    path: str
