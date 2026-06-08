"""ASGI app for Playwright e2e tests.

Boots the real FastAPI app with a FakeGallery so the worker can run end-to-end
without hitting the network. Launch with:

    cd backend && PYTHONPATH=. uv run uvicorn tests.e2e_server:app --port 8000
"""

from __future__ import annotations

import os
import time

from gallery_dl.exception import StopExtraction

from backend.config import Settings
from backend.main import create_app

from .fakes import FakeGallery, FakeGalleryConfig

_E2E_DATA_DIR = os.environ.get("WEBUI_DATA_DIR", "./data-e2e")


def _settings() -> Settings:
    from pathlib import Path

    return Settings(
        data_dir=Path(_E2E_DATA_DIR).resolve(),
        host=os.environ.get("WEBUI_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEBUI_PORT", "8000")),
    )


# The shared config the test seeds with known-good URLs.
config = FakeGalleryConfig()
config.extractor_for["https://e2e.test/ok"] = "e2etest"
config.manifest_for["https://e2e.test/ok"] = [
    "e2etest/chapter-1/001.jpg",
    "e2etest/chapter-1/002.jpg",
    "e2etest/chapter-2/001.jpg",
]
# A slow variant so the UI can show "running" state.
config.extractor_for["https://e2e.test/slow"] = "e2etest"
config.manifest_for["https://e2e.test/slow"] = [f"e2etest/slow/{i:03d}.jpg" for i in range(1, 6)]
# A longer-running variant for the design-screenshot capture — multiple
# chapters so the progress card shows partial completion mid-run.
config.extractor_for["https://e2e.test/very-slow"] = "e2etest"
config.manifest_for["https://e2e.test/very-slow"] = [
    f"e2etest/chapter-{c}/{i:03d}.jpg" for c in range(1, 5) for i in range(1, 8)
]
# An unsupported URL.
config.extractor_for["https://e2e.test/unsupported"] = None


class _SlowFakeGallery(FakeGallery):
    """A FakeGallery that sleeps between files for the /slow URL only."""

    def run_download(self, url, on_file_complete=None, skip_chapter=None):  # type: ignore[override]
        self.download_calls.append(url)
        rels = self._config.manifest_for.get(url, [])
        for rel in rels:
            manga, chapter = self._chapter_for(url, rel)
            if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
                continue
            if self._config.write_files:
                p = self._downloads_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x")
            if on_file_complete is not None:
                try:
                    on_file_complete(rel)
                except StopExtraction:
                    break
            if "slow" in url:
                time.sleep(0.4)
        records = []
        for rec in self._config.records_for.get(url, []):
            if (
                skip_chapter is not None
                and rec.manga
                and rec.chapter
                and skip_chapter(rec.manga, rec.chapter)
            ):
                continue
            records.append(rec)
        return 0, records, dict(self._config.chapter_errors_for.get(url, {}))


def _gallery_factory(settings: Settings) -> FakeGallery:
    return _SlowFakeGallery(settings, config=config)


app = create_app(
    settings_factory=_settings,
    gallery_factory=_gallery_factory,
    serve_frontend=False,
)
