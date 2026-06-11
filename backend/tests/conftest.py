from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database import open_database
from backend.main import create_app

from .fakes import FakeGallery, FakeGalleryConfig


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", host="127.0.0.1", port=0)


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[aiosqlite.Connection]:
    """A fresh schema-installed SQLite connection, for tests that exercise the
    service layer directly (without the app/TestClient)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = await open_database(settings.data_dir / "jobs.db")
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def gallery_config() -> FakeGalleryConfig:
    return FakeGalleryConfig()


@pytest.fixture
def client(
    settings: Settings,
    gallery_config: FakeGalleryConfig,
) -> Iterator[TestClient]:
    app = create_app(
        settings_factory=lambda: settings,
        gallery_factory=lambda s: FakeGallery(s, config=gallery_config),
        serve_frontend=False,
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gallery(client: TestClient) -> FakeGallery:
    """The FakeGallery the app's lifespan constructed. Depends on `client` so
    the lifespan has already run by the time the test sees this."""
    return client.app.state.gallery
