"""Test doubles used by both unit and integration tests."""

import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from gallery_dl.exception import StopExtraction

from backend.comic_metadata import FileRecord, earliest_date
from backend.config import Settings
from backend.downloads.gallery import MetadataResult, SkipChapterFn


class FakeGalleryConfig:
    """Mutable container so tests can configure the fake at any point.

    The FakeGallery reads from this object on each call, so a test fixture
    can hand the config to the gallery factory and then have the test mutate
    it afterwards — useful with FastAPI's TestClient, which builds the app
    (and thus the gallery) before the test body runs.
    """

    def __init__(self) -> None:
        self.extractor_for: dict[str, str | None] = {}
        # `manifest_for` is per-URL list of file relpaths the fake "downloads"
        # (also drives the chapter list returned by extract_metadata: each
        # unique parent dir is one chapter unless `chapter_dates_for` is set
        # explicitly).
        self.manifest_for: dict[str, list[str]] = {}
        # Optional per-URL metadata; when set, FakeGallery.run_download returns
        # these as records. When unset, no records are emitted.
        self.records_for: dict[str, list[FileRecord]] = {}
        # Optional per-URL series name surfaced by extract_metadata.
        self.series_name_for: dict[str, str | None] = {}
        # Optional per-URL series publication status (already normalised to a
        # Komga label) surfaced by extract_metadata.
        self.series_status_for: dict[str, str | None] = {}
        # Optional per-URL series tags/genres surfaced by extract_metadata.
        self.series_tags_for: dict[str, list[str] | None] = {}
        # Optional per-URL chapter-date map surfaced by the metadata-only
        # sim pass (extract_metadata). Keys are (manga, chapter) tuples,
        # values are ISO YYYY-MM-DD strings. Falls back to the parent dirs
        # of `manifest_for` paths when unset.
        self.chapter_dates_for: dict[str, dict[tuple[str, str], str]] = {}
        # Optional per-URL captured per-chapter errors (chapter name -> reason),
        # surfaced by run_download to exercise outcome reconciliation.
        self.chapter_errors_for: dict[str, dict[str, str]] = {}
        # Optional per-URL gate: when set, run_download blocks until the event
        # fires (or a safety timeout), keeping the job deterministically
        # "running" while a test pokes at concurrent-download behaviour.
        # run_download executes via asyncio.to_thread, so blocking is safe.
        self.gate_for: dict[str, threading.Event] = {}
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
        self.metadata_calls: list[str] = []
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

    def extract_metadata(self, url: str) -> MetadataResult:
        self.metadata_calls.append(url)
        dates = self._config.chapter_dates_for.get(url)
        if dates is None:
            dates = self._derive_chapter_dates(url)
        return MetadataResult(
            series_name=self._config.series_name_for.get(url),
            series_status=self._config.series_status_for.get(url),
            series_tags=self._config.series_tags_for.get(url),
            chapter_dates=dict(dates),
            earliest_chapter_date=earliest_date(dates.values()),
        )

    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> tuple[int, list[FileRecord], dict[str, str]]:
        self.download_calls.append(url)
        gate = self._config.gate_for.get(url)
        if gate is not None:
            # Timeout so a test that forgets to set the gate can't wedge the
            # worker thread past its own failure.
            gate.wait(timeout=10)
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
        return 0, emitted_records, dict(self._config.chapter_errors_for.get(url, {}))

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

    def _derive_chapter_dates(self, url: str) -> dict[tuple[str, str], str]:
        """Synthesise a chapter_dates dict from the URL's manifest_for entries
        when the test didn't set chapter_dates_for explicitly. Maps each
        unique parent directory of a manifest path to a (manga, chapter)
        key — manga taken from `records_for` when present, else "" — so the
        worker's chapter-list extraction has something to walk."""
        out: dict[tuple[str, str], str] = {}
        for rel in self._config.manifest_for.get(url, []):
            parent = str(PurePosixPath(rel).parent)
            if parent == ".":
                parent = ""
            manga, chapter = self._chapter_for(url, rel)
            key = (manga, chapter or parent)
            out.setdefault(key, "")
        return out
