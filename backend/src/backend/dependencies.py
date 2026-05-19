"""Cross-domain FastAPI dependencies.

Domain-specific dependencies live next to their routes (see
`backend.downloads.dependencies` etc.); only deps that are needed in multiple
domains are surfaced here.
"""

from __future__ import annotations

from typing import Annotated

import aiosqlite
from fastapi import Depends, Request

from backend.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> aiosqlite.Connection:
    return request.app.state.db


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]
