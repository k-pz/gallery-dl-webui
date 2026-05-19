from pathlib import Path

import aiosqlite
import pytest

from backend.app_config import service
from backend.database import open_database


@pytest.fixture
async def db(tmp_path: Path):
    conn = await open_database(tmp_path / "jobs.db")
    try:
        yield conn
    finally:
        await conn.close()


async def test_app_config_round_trip(db: aiosqlite.Connection) -> None:
    assert await service.get_all(db) == {}

    await service.set_many(db, {"postprocess_root": "/tmp/media", "delete_raw_after_pack": True})
    cfg = await service.get_all(db)
    assert cfg == {"postprocess_root": "/tmp/media", "delete_raw_after_pack": True}

    await service.set_many(db, {"postprocess_root": None})
    cfg = await service.get_all(db)
    assert cfg == {"postprocess_root": None, "delete_raw_after_pack": True}


async def test_remember_output_dir_dedupes_and_orders(db: aiosqlite.Connection) -> None:
    after = await service.remember_output_dir(db, "/m/a")
    assert after == ["/m/a"]
    after = await service.remember_output_dir(db, "/m/b")
    assert after == ["/m/b", "/m/a"]
    after = await service.remember_output_dir(db, "/m/a")
    assert after == ["/m/a", "/m/b"]
