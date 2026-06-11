import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gallery_dl import config, extractor, output
from gallery_dl.exception import StopExtraction
from gallery_dl.job import DownloadJob, SimulationJob

from backend.comic_metadata import (
    FileRecord,
    chapter_with_minor,
    coerce_record_from_kwdict,
    date_iso,
    earliest_date,
    normalize_series_status,
    normalize_tags,
)
from backend.config import Settings
from backend.downloads.capture import ChapterErrorCollector

# Predicate: given (manga, chapter) from a gallery-dl kwdict, returns True if
# the chapter is already represented as a CBZ in the postprocess output dir,
# i.e. the worker should not re-download or include it in the manifest.
SkipChapterFn = Callable[[str, str], bool]


@dataclass
class MetadataResult:
    """What a metadata-only sim pass discovers about a series.

    `series_name` is the first non-empty `manga` (or `series`) value seen in any
    directory's kwdict — gallery-dl exposes a per-source metadata dict before
    pages are enumerated, so we capture it without running a real download.

    `series_status` is the first kwdict-supplied publication status we manage
    to map to a Komga-compatible label (one of `SERIES_STATUSES`). `None` when
    no directory exposed a recognised status — leaves the target's existing
    value untouched.

    `series_tags` is the first non-empty list of tags/genres surfaced by any
    directory's kwdict (gallery-dl extractors variously expose this as `tags`,
    `genres`, or `genre`). `None` when no directory exposed any — leaves the
    target's existing value untouched.

    `chapter_dates` maps `(manga_name, chapter_string)` to an ISO `YYYY-MM-DD`
    date when the extractor surfaced one — extractors that derive chapter
    dates from the chapter page itself (kaliscan et al.) won't populate this
    until the chapter has been visited; mangadex-style API extractors fill it
    from the series-level chapter list. `len(chapter_dates)` is the discovered
    chapter count.

    `earliest_chapter_date` is the minimum of `chapter_dates` values — the
    series' first-publication date as far as the source knows it. `None` when
    no chapter exposed a usable date.
    """

    series_name: str | None = None
    series_status: str | None = None
    series_tags: list[str] | None = None
    chapter_dates: dict[tuple[str, str], str] = field(default_factory=dict)
    earliest_chapter_date: str | None = None


def _inherit_shared_state(child: Any, parent: Any, *attrs: str) -> bool:
    """If parent is the same kind as child, copy the named attrs over.

    Gallery-dl spawns child jobs for nested extractors; subclasses below use
    this to forward their accumulator state (manifests, callbacks, records)
    so a single run aggregates everything the root started with.
    Returns True when state was inherited so callers know to skip fresh init.
    """
    if not isinstance(parent, type(child)):
        return False
    for name in attrs:
        setattr(child, name, getattr(parent, name))
    return True


class _ProgressDownloadJob(DownloadJob):
    """DownloadJob variant that notifies a callback after each file completes
    and accumulates per-file metadata records for postprocessing.

    Child jobs spawned for nested extractors share the same callback and
    records list so a single run reports every downloaded file.
    """

    _on_file_complete: Callable[[str], None]
    _downloads_base: str
    _records: list[FileRecord]
    _skip_chapter: SkipChapterFn | None
    _chapter_ctx: list[str]

    def __init__(
        self,
        url: Any,
        parent: DownloadJob | None = None,
        *,
        on_file_complete: Callable[[str], None] | None = None,
        downloads_base: str | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> None:
        super().__init__(url, parent)
        if not _inherit_shared_state(
            self,
            parent,
            "_on_file_complete",
            "_downloads_base",
            "_records",
            "_skip_chapter",
            "_chapter_ctx",
        ):
            assert on_file_complete is not None and downloads_base is not None
            self._on_file_complete = on_file_complete
            self._downloads_base = downloads_base
            self._records = []
            self._skip_chapter = skip_chapter
            self._chapter_ctx = [""]

    def _track_chapter(self, kwdict: dict[str, Any]) -> str:
        """Record the current chapter in `_chapter_ctx` and return its name."""
        chapter = chapter_with_minor(kwdict)
        if chapter:
            self._chapter_ctx[0] = chapter
        return chapter

    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        self._track_chapter(kwdict)
        super().handle_directory(kwdict)

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        chapter = self._track_chapter(kwdict)
        if self._skip_chapter is not None:
            manga = str(kwdict.get("manga") or "")
            if manga and chapter and self._skip_chapter(manga, chapter):
                pathfmt = self.pathfmt
                if pathfmt is not None:
                    pathfmt.set_filename(kwdict)
                self.handle_skip()
                return
        super().handle_url(url, kwdict)
        pathfmt = self.pathfmt
        if pathfmt is None:
            return
        full = pathfmt.directory + pathfmt.filename
        rel = full[len(self._downloads_base) :] if full.startswith(self._downloads_base) else full
        # Snapshot metadata immediately — gallery-dl mutates kwdict over the
        # download lifecycle. The records list is appended to from the worker
        # thread (run via asyncio.to_thread); the event loop only reads it
        # after the thread resolves, so no synchronisation is required.
        self._records.append(coerce_record_from_kwdict(kwdict, Path(full)))
        self._on_file_complete(rel)


class _MetadataSimulationJob(SimulationJob):
    """Sim job that captures kwdict-level metadata without descending into chapters.

    Most manga-level extractors already pack per-chapter `manga` / `chapter` /
    `date` / `status` / `tags` into the kwdict carried by every
    `Message.Queue` they yield — weebcentral, for example, builds these out
    of its single `/series/{id}/full-chapter-list` fetch. When that's the
    case `handle_queue` banks the data and returns without spawning a child
    chapter extractor, skipping the two HTTP requests per chapter (chapter
    page + images list) and the rate-limit sleep between them.

    Extractors that only surface dates on the chapter page itself fall
    through to the default `handle_queue`, which spawns a child job whose
    `handle_directory` then captures what's there and raises
    `StopExtraction`. `GalleryExtractor.items` calls `images()` before
    yielding Directory, so the fallback path still pays the chapter-page +
    images fetch — it's strictly an improvement for queue-rich extractors
    and a no-op cost-wise for the rest.

    For top-level chapter URLs (no parent manga extractor to queue from),
    `handle_directory` is reached directly and the StopExtraction trick
    keeps us from advancing into Url yields.
    """

    _series_box: list[str | None]
    _status_box: list[str | None]
    _tags_box: list[list[str] | None]
    _dates_box: list[dict[tuple[str, str], str]]

    def __init__(self, url: Any, parent: SimulationJob | None = None) -> None:
        super().__init__(url, parent)
        if not _inherit_shared_state(
            self, parent, "_series_box", "_status_box", "_tags_box", "_dates_box"
        ):
            self._series_box = [None]
            self._status_box = [None]
            self._tags_box = [None]
            self._dates_box = [{}]

    def handle_queue(self, url: str, kwdict: dict[str, Any]) -> None:
        if self._capture(kwdict):
            return
        # Queue-level kwdict lacked one of manga/chapter/date — descend so
        # the child's handle_directory can try to capture from the chapter
        # page instead.
        super().handle_queue(url, kwdict)

    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        self._capture(kwdict)
        # Reached for top-level chapter URLs and for the fallback descent
        # above. Either way, abandon items() before any Url yields so we
        # don't enumerate (or fetch) pages.
        raise StopExtraction()

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        # Unreachable in normal flow (handle_directory raises before any URLs
        # arrive). Guard anyway: some extractors yield Url without a prior
        # Directory (e.g. follow links), and we never want a metadata pass to
        # touch the filesystem.
        return

    def _capture(self, kwdict: dict[str, Any]) -> bool:
        """Bank series-level + per-chapter fields from a kwdict.

        Returns True only when manga + chapter + date were all present —
        the signal that this chapter's full info is already in hand and the
        caller can skip descending into a child extractor.
        """
        if self._series_box[0] is None:
            for key in ("manga", "series", "title"):
                value = kwdict.get(key)
                if isinstance(value, str) and value.strip():
                    self._series_box[0] = value.strip()
                    break
        if self._status_box[0] is None:
            for key in ("status", "publication_status"):
                value = kwdict.get(key)
                if isinstance(value, str) and value.strip():
                    normalised = normalize_series_status(value)
                    if normalised:
                        self._status_box[0] = normalised
                    break
        if self._tags_box[0] is None:
            for key in ("tags", "genres", "genre"):
                raw = kwdict.get(key)
                if isinstance(raw, list):
                    candidates = [v for v in raw if isinstance(v, str)]
                elif isinstance(raw, str) and raw.strip():
                    candidates = [raw]
                else:
                    continue
                cleaned = normalize_tags(candidates)
                if cleaned:
                    self._tags_box[0] = cleaned
                    break
        manga = str(kwdict.get("manga") or "").strip()
        chapter = chapter_with_minor(kwdict)
        date = date_iso(kwdict.get("date"))
        if manga and chapter and date:
            self._dates_box[0].setdefault((manga, chapter), date)
            return True
        return False


class Gallery:
    """Thin wrapper around gallery-dl, scoped to one Settings instance.

    Configures gallery-dl's global state on construction. Constructing more
    than one instance per process is supported but will overwrite the previous
    configuration.
    """

    _configured = False

    def __init__(self, settings: Settings) -> None:
        self._downloads_dir = settings.downloads_dir
        if not Gallery._configured:
            output.initialize_logging(logging.INFO)
            Gallery._configured = True
        config.set(("extractor",), "base-directory", str(settings.downloads_dir))
        config.set(("extractor",), "archive", str(settings.archive_db_path))

    @property
    def downloads_dir(self) -> Path:
        return self._downloads_dir

    @staticmethod
    def find_extractor(url: str) -> str | None:
        try:
            found = extractor.find(url)
        except Exception:
            return None
        if found is None:
            return None
        return getattr(found, "category", None)

    def extract_metadata(self, url: str) -> MetadataResult:
        """Run a metadata-only sim: capture per-chapter and series-level
        kwdict fields without enumerating page URLs.

        Used by the download worker to discover the chapter list (and seed
        series metadata) before a real download starts, and by the regen
        maintenance job to rediscover series status, tags, and chapter
        release dates against the upstream extractor.
        """
        job = _MetadataSimulationJob(url)
        job.run()
        chapter_dates = dict(job._dates_box[0])
        return MetadataResult(
            series_name=job._series_box[0],
            series_status=job._status_box[0],
            series_tags=job._tags_box[0],
            chapter_dates=chapter_dates,
            earliest_chapter_date=earliest_date(chapter_dates.values()),
        )

    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> tuple[int, list[FileRecord], dict[str, str]]:
        """Run a real download. Returns (exit_code, per-file metadata records,
        per-chapter error reasons).

        Records are only collected when an `on_file_complete` callback is
        supplied (the worker always supplies one); otherwise the list is empty.
        `skip_chapter`, when set, causes the download job to short-circuit
        URLs whose chapter the callable says is already packed. Per-chapter
        errors are captured by a logging handler attached to the root logger
        for the duration of the run (see `ChapterErrorCollector`).
        """
        if on_file_complete is None:
            return DownloadJob(url).run(), [], {}
        base = str(self._downloads_dir).rstrip(os.sep) + os.sep
        job = _ProgressDownloadJob(
            url,
            on_file_complete=on_file_complete,
            downloads_base=base,
            skip_chapter=skip_chapter,
        )
        collector = ChapterErrorCollector(job._chapter_ctx, threading.get_ident())
        root = logging.getLogger()
        root.addHandler(collector)
        try:
            exit_code = job.run()
        finally:
            root.removeHandler(collector)
        return exit_code, job._records, dict(collector.errors)
