import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gallery_dl import config, extractor, output
from gallery_dl.exception import StopExtraction
from gallery_dl.job import DownloadJob, SimulationJob

from backend.config import Settings
from backend.downloads.postprocess import (
    FileRecord,
    chapter_with_minor,
    coerce_record_from_kwdict,
    date_iso,
    normalize_series_status,
    normalize_tags,
)

# Predicate: given (manga, chapter) from a gallery-dl kwdict, returns True if
# the chapter is already represented as a CBZ in the postprocess output dir,
# i.e. the worker should not re-download or include it in the manifest.
SkipChapterFn = Callable[[str, str], bool]


@dataclass
class MetadataResult:
    """What a metadata-only sim pass discovers about a series.

    `series_name`, `series_status`, and `series_tags` mirror the same fields
    on `Manifest` (sourced from the same kwdict). `chapter_dates` maps
    `(manga_name, chapter_string)` to an ISO `YYYY-MM-DD` date when the
    extractor surfaced one — extractors that derive chapter dates from the
    chapter page itself (kaliscan et al.) won't populate this until the
    chapter has been visited; mangadex-style API extractors fill it from the
    series-level chapter list.
    """

    series_name: str | None = None
    series_status: str | None = None
    series_tags: list[str] | None = None
    chapter_dates: dict[tuple[str, str], str] = field(default_factory=dict)


@dataclass
class Manifest:
    """Result of a simulation pass: which files we expect, plus discovered metadata.

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
    """

    paths: list[str]
    series_name: str | None = None
    series_status: str | None = None
    series_tags: list[str] | None = None


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


class _ManifestSimulationJob(SimulationJob):
    """SimulationJob variant that records every would-be file path.

    Child jobs spawned for nested extractors share the same _manifest list and
    series-name box so a single run accumulates all expected paths and the
    first-seen series name.
    """

    _manifest: list[tuple[str, str, str]]
    _series_box: list[str | None]
    _status_box: list[str | None]
    _tags_box: list[list[str] | None]

    def __init__(self, url: Any, parent: SimulationJob | None = None) -> None:
        super().__init__(url, parent)
        if not _inherit_shared_state(
            self, parent, "_manifest", "_series_box", "_status_box", "_tags_box"
        ):
            self._manifest = []
            self._series_box = [None]
            self._status_box = [None]
            self._tags_box = [None]

    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        # SimulationJob.handle_directory only calls initialize() and never sets
        # pathfmt.directory, so the recorded paths would be missing the per-job
        # directory prefix. Mirror DownloadJob.handle_directory's behavior.
        if self.pathfmt is None:
            self.initialize(kwdict)
        else:
            self.pathfmt.set_directory(kwdict)
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
            # Extractors variously call this `tags`, `genres`, or `genre`
            # (mangapark uses the singular for what is in fact a list).
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

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        pathfmt = self.pathfmt
        assert pathfmt is not None
        ext = kwdict["extension"] or "jpg"
        kwdict["extension"] = pathfmt.extension_map(ext, ext)
        if self.archive is not None and self._archive_write_skip:
            self.archive.add(kwdict)
        filename = pathfmt.build_filename(kwdict)
        manga = str(kwdict.get("manga") or "")
        chapter = chapter_with_minor(kwdict)
        self._manifest.append((pathfmt.directory + filename, manga, chapter))


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
        ):
            assert on_file_complete is not None and downloads_base is not None
            self._on_file_complete = on_file_complete
            self._downloads_base = downloads_base
            self._records = []
            self._skip_chapter = skip_chapter

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        if self._skip_chapter is not None:
            manga = str(kwdict.get("manga") or "")
            chapter = chapter_with_minor(kwdict)
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
    """Sim job that captures kwdict-level metadata then bails out per chapter.

    The chapter-level kwdict surfaced via `handle_directory` already carries
    the manga + chapter + date + tags + status fields we need; the subsequent
    `Message.Url` yields force the extractor to fetch the chapter's page list
    (e.g. mangadex's `athome_server`), which we don't need for metadata
    rediscovery. Raising `StopExtraction` after the Directory yield abandons
    the current extractor's generator without advancing it past that point —
    the parent (manga-level) extractor catches the exception and continues to
    the next chapter Queue message.

    For HTML-driven extractors that fetch the chapter page *before* yielding
    Directory (most kaliscan/manganelo-style sites), no network is saved —
    but no extra cost is paid either. API-driven extractors (mangadex) save
    one page-list fetch per chapter.
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

    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        # Capture in-place (these mirror _ManifestSimulationJob.handle_directory
        # except we don't need to populate pathfmt — we won't yield any URLs).
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
        # Skip the rest of this extractor's items() generator — the chapter
        # data we needed is now banked. The parent (manga-level) extractor's
        # for-loop over Queue messages keeps going past the caught exception.
        raise StopExtraction()

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        # Unreachable in normal flow (handle_directory raises before any URLs
        # arrive). Guard anyway: some extractors yield Url without a prior
        # Directory (e.g. follow links), and we never want a metadata pass to
        # touch the filesystem.
        return


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

    def extract_manifest(
        self,
        url: str,
        skip_chapter: SkipChapterFn | None = None,
    ) -> Manifest:
        """Run gallery-dl in simulate mode; return the expected files (as paths
        relative to the configured downloads directory) plus the first series
        name we observed in any directory's metadata.

        When `skip_chapter` is supplied, manifest entries belonging to chapters
        the callable identifies as already-done are omitted, so progress
        accounting reflects only the work the real download will perform.
        """
        job = _ManifestSimulationJob(url)
        job.run()
        base = str(self._downloads_dir).rstrip(os.sep) + os.sep
        paths: list[str] = []
        for full, manga, chapter in job._manifest:
            if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
                continue
            paths.append(full[len(base) :] if full.startswith(base) else full)
        return Manifest(
            paths=paths,
            series_name=job._series_box[0],
            series_status=job._status_box[0],
            series_tags=job._tags_box[0],
        )

    def extract_metadata(self, url: str) -> MetadataResult:
        """Run a metadata-only sim: capture per-chapter and series-level
        kwdict fields without enumerating page URLs.

        Used by the regen maintenance job to rediscover series status, tags,
        and chapter release dates against the upstream extractor — the
        normal `extract_manifest` would also work but spends time fetching
        page lists for chapters we already have on disk.
        """
        job = _MetadataSimulationJob(url)
        job.run()
        return MetadataResult(
            series_name=job._series_box[0],
            series_status=job._status_box[0],
            series_tags=job._tags_box[0],
            chapter_dates=dict(job._dates_box[0]),
        )

    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> tuple[int, list[FileRecord]]:
        """Run a real download. Returns (exit_code, per-file metadata records).

        Records are only collected when an `on_file_complete` callback is
        supplied (the worker always supplies one); otherwise the list is empty.
        `skip_chapter`, when set, causes the download job to short-circuit
        URLs whose chapter the callable says is already packed.
        """
        if on_file_complete is None:
            return DownloadJob(url).run(), []
        base = str(self._downloads_dir).rstrip(os.sep) + os.sep
        job = _ProgressDownloadJob(
            url,
            on_file_complete=on_file_complete,
            downloads_base=base,
            skip_chapter=skip_chapter,
        )
        exit_code = job.run()
        return exit_code, job._records
