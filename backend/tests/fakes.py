"""Test doubles used by both unit and integration tests."""

from collections.abc import Callable
from pathlib import Path

from backend.settings import Settings


class FakeGalleryConfig:
    """Mutable container so tests can configure the fake at any point.

    The FakeGallery reads from this object on each call, so a test fixture
    can hand the config to the gallery factory and then have the test mutate
    it afterwards — useful with FastAPI's TestClient, which builds the app
    (and thus the gallery) before the test body runs.
    """

    def __init__(self) -> None:
        self.extractor_for: dict[str, str | None] = {}
        self.manifest_for: dict[str, list[str]] = {}
        self.default_extractor: str | None = "fake"
        self.write_files: bool = True


class FakeGallery:
    """In-memory stand-in for Gallery."""

    def __init__(
        self,
        settings: Settings,
        *,
        config: FakeGalleryConfig | None = None,
    ) -> None:
        self._downloads_dir = settings.downloads_dir
        self._config = config or FakeGalleryConfig()
        self.extract_calls: list[str] = []
        self.download_calls: list[str] = []

    @property
    def config(self) -> FakeGalleryConfig:
        return self._config

    @property
    def downloads_dir(self) -> Path:
        return self._downloads_dir

    def find_extractor(self, url: str) -> str | None:
        if url in self._config.extractor_for:
            return self._config.extractor_for[url]
        return self._config.default_extractor

    def extract_manifest(self, url: str) -> list[str]:
        self.extract_calls.append(url)
        return list(self._config.manifest_for.get(url, []))

    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
    ) -> int:
        self.download_calls.append(url)
        for rel in self._config.manifest_for.get(url, []):
            if self._config.write_files:
                p = self._downloads_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x")
            if on_file_complete is not None:
                on_file_complete(rel)
        return 0
