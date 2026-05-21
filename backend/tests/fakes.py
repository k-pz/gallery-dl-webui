"""Test doubles used by both unit and integration tests."""

from collections.abc import Callable
from pathlib import Path

from gallery_dl.exception import StopExtraction

from backend.config import Settings
from backend.downloads.gallery import Manifest, SkipChapterFn
from backend.downloads.postprocess import FileRecord


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
        # Optional per-URL metadata; when set, FakeGallery.run_download returns
        # these as records. When unset, no records are emitted.
        self.records_for: dict[str, list[FileRecord]] = {}
        # Optional per-URL series name surfaced by extract_manifest, mirroring
        # the metadata gallery-dl's simulation job exposes via kwdict.
        self.series_name_for: dict[str, str | None] = {}
        # Optional per-URL series publication status (already normalised to a
        # Komga label) surfaced by extract_manifest.
        self.series_status_for: dict[str, str | None] = {}
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

    def extract_manifest(
        self,
        url: str,
        skip_chapter: SkipChapterFn | None = None,
    ) -> Manifest:
        self.extract_calls.append(url)
        paths: list[str] = []
        for rel in self._config.manifest_for.get(url, []):
            manga, chapter = self._chapter_for(url, rel)
            if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
                continue
            paths.append(rel)
        return Manifest(
            paths=paths,
            series_name=self._config.series_name_for.get(url),
            series_status=self._config.series_status_for.get(url),
        )

    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> tuple[int, list[FileRecord]]:
        self.download_calls.append(url)
        emitted_records: list[FileRecord] = []
        for rel in self._config.manifest_for.get(url, []):
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
                    # Mirror gallery-dl: StopExtraction unwinds the job cleanly
                    # and run() returns the current status code.
                    break
        for rec in self._config.records_for.get(url, []):
            if (
                skip_chapter is not None
                and rec.manga
                and rec.chapter
                and skip_chapter(rec.manga, rec.chapter)
            ):
                continue
            emitted_records.append(rec)
        return 0, emitted_records

    def _chapter_for(self, url: str, relpath: str) -> tuple[str, str]:
        """Look up (manga, chapter) for a manifest entry from records_for, when
        available. Lets tests exercise the skip-chapter path without wiring up
        a full kwdict pipeline."""
        for rec in self._config.records_for.get(url, []):
            try:
                rel = str(rec.path.relative_to(self._downloads_dir))
            except ValueError:
                continue
            if rel == relpath:
                return rec.manga, rec.chapter
        return "", ""
