# Download pipeline

How one download flows from `pending` to `completed` + packed CBZ. Covers
the worker coroutine, the gallery-dl integration, the postprocess step, and
how per-chapter progress is computed.

The HTTP entry points and status taxonomy live in
[Backend](backend.md#downloads). For the end-to-end traces (including the
cancel and re-poll paths) see [Lifecycles](lifecycles.md).

## The Worker

`downloads/worker.py`

A pool of N long-running coroutines ("slots") driven by an `asyncio.Event`
(`_wakeup`). The slot count comes from `app_config.max_concurrent_downloads`
(default 2, hard ceiling 16) and is read once at startup by a bootstrap
supervisor task; bumping it requires a restart.

Each slot loops:

```
while not stop:
    job = await service.claim_next_pending(db)   # FIFO over id
    if job is None:
        await self._wakeup.wait()                # idle
        continue
    self._current_id = job.id
    self._cancel_requested = False
    try:
        await self._process(job)
    finally:
        clear cancel state
```

`_process(job)`:

1. **Build `skip_chapter` predicate** if this is a watched target with a
   resolvable output dir. The predicate is invoked by gallery-dl for every
   page URL; on first call per `(manga, chapter)` it answers from disk
   (`chapter_already_packed(output_dir, manga, chapter)`), then memoises.
2. **Simulation pass** (`asyncio.to_thread(gallery.extract_manifest, ...)`).
   Returns `Manifest(paths, series_name, series_status, series_tags)`. The
   manifest is saved to `download_files` (and `files_expected` /
   `chapters_total` are set). `series_name` updates the target's `name`;
   `series_status` (when the extractor surfaced one) is normalised to a
   Komga label and written to `targets.series_status`; `series_tags`
   (when the extractor surfaced tags/genres) is written to `targets.tags`.
   Both metadata writes are fill-only — they never overwrite a user-set
   value, so the manual PATCH in the UI always wins.
3. If cancel was requested between extract and the real run, mark cancelled
   and return.
4. **Real download** (`asyncio.to_thread(gallery.run_download, ...)`):
   - `service.mark_running(...)` → status flips to `running`.
   - `live_progress.start(job.id)`.
   - Run gallery-dl with a callback that records each completed relpath and
     raises `StopExtraction` if the cancel flag is set.
   - On return, count files actually on disk (`count_present`).
   - Persist via `finish_job` (status = `completed`/`failed` from exit code)
     or `mark_cancelled`.
   - `live_progress.clear(job.id)`.
5. If `records` carry a `manga` field, refine `targets.name` from it (the
   real pass has better metadata than the simulation).
6. If `exit_code == 0` and not cancelled, run `_run_postprocess(...)`:
   - Look up `postprocess_root` and `output_dir` from app_config / the job.
   - Re-validate the output dir is under the root.
   - `postprocess.run(...)` — see [Postprocessing → CBZ](#postprocessing--cbz).
   - Persist `postprocess_status`, `postprocess_chapters_packed`,
     `postprocess_error`.

On any exception during 1–4, `_handle_failure(...)` logs, counts whatever
landed on disk, and persists `mark_failed(error=repr(exc))`.

**Cancellation contract:** `request_cancel(id)` looks the id up in
`Worker._cancel_flags` (per-job dict, keyed while the slot is processing
that download) and flips the value to `True`. The worker thread reads that
bool inside the per-file callback; setting a bool from one coroutine and
reading it from one thread is GIL-atomic and is the only synchronisation
the worker needs (single-writer / single-reader). For a *pending* (not-yet
-started) job, the route also flips the row to `cancelled` directly via
`cancel_pending`.

**Connection lock**: every multi-statement DB sequence inside the worker is
wrapped in `async with self._db_lock` (a process-wide
`asyncio.Lock` shared with the poller and maintenance worker). One
aiosqlite connection serves the whole app, and an open cursor from one
coroutine otherwise blocks another's `commit()` mid-transaction.

## gallery-dl integration

`downloads/gallery.py`

`Gallery` is a thin façade around three gallery-dl entry points:

- `extractor.find(url)` → `Gallery.find_extractor(url)`. Returns the
  `category` string (e.g. `"mangadex"`) or `None`.
- `SimulationJob` → `Gallery.extract_manifest(url, skip_chapter)`. We don't
  use it raw — we subclass it.
- `DownloadJob` → `Gallery.run_download(url, on_file_complete, skip_chapter)`.
  Also subclassed.

**Why subclass:**

- `_ManifestSimulationJob.handle_directory` overrides gallery-dl's no-op
  simulation to actually populate `pathfmt.directory`. Without it, recorded
  paths are missing their per-chapter directory prefix and progress
  accounting can't match files to chapters. It also opportunistically
  captures the first `manga` / `series` / `title` value seen in any
  kwdict — that becomes `Manifest.series_name` — the first kwdict
  `status` / `publication_status` that maps to a Komga label
  (`normalize_series_status`), which becomes `Manifest.series_status`,
  and the first kwdict `tags` / `genres` / `genre` list, which becomes
  `Manifest.series_tags`. All three are observed once per run: the sim
  pass is the earliest point where series-level metadata is exposed, so
  the worker can persist them before any pages are written.
- `_ManifestSimulationJob.handle_url` records `(full_path, manga, chapter)`
  for every would-be file. Used both to build the manifest and to apply the
  `skip_chapter` predicate so manifest entries belonging to already-packed
  chapters are omitted (so progress shows real remaining work, not
  re-counted history).
- `_ProgressDownloadJob.handle_url` does the real download via
  `super().handle_url`, then captures a snapshot of the file's metadata
  (`coerce_record_from_kwdict`) into a `_records` list and fires the
  `on_file_complete` callback. When `skip_chapter` returns true for a URL,
  it calls `handle_skip()` instead, which keeps gallery-dl's `archive`
  accounting consistent without writing the file.

Gallery-dl spawns *child* jobs for nested extractors (e.g. a series page
that links to per-chapter pages). The subclasses use `_inherit_shared_state`
so a child job shares its parent's manifest list / records list / callbacks
— a single top-level `.run()` yields one aggregated result.

`Gallery.__init__` calls `config.set(("extractor",), "base-directory", ...)`
and `..., "archive", ...)`. These are *process-global* in gallery-dl, so
constructing more than one `Gallery` per process overwrites the previous
settings. In tests we use `FakeGallery` instead (`tests/fakes.py`), which
honours the same interface but writes files to disk without calling
gallery-dl.

## Postprocessing → CBZ

`downloads/postprocess.py`

Postprocessing groups the worker's `FileRecord` list by parent directory,
collects each into a `ChapterRecord`, and packs each chapter into a Zip
archive with `.cbz` extension and a `ComicInfo.xml` payload.

Chapter target paths are reserved **sequentially** before packing kicks off
— stems are deterministic and reused across runs, so two chapters resolving
to the same name would race on disk if they were both computed in parallel.
Once targets are reserved, packing runs through an `asyncio.Semaphore` sized
by `app_config.max_parallel_postprocess` (default 3, ceiling 16); zipfile
releases the GIL during deflate, so a small handful of threads is enough to
overlap pack-then-rmtree on adjacent chapters.

Naming convention (Komga-friendly):

```
<output_dir>/<Series>/<Series> - cNNN[ - Title].cbz
```

Chapter number formatting:

- Integer < 1000 → zero-padded to 3 digits (`c042`).
- Integer ≥ 1000 → bare integer (`c1000`).
- Fractional → `c042.5` (whole zero-padded if < 1000).
- Non-numeric → sanitised string.

`sanitize(name)` replaces `[\\/:*?"<>|\x00-\x1f]` with `_`, strips trailing
dots/whitespace, falls back to `"_"`.

Collision handling: if the target path exists, append ` (1)`…` (999)` until
free. `chapter_already_packed(output_dir, manga, chapter)` matches the same
stem family for the watched-target skip logic.

Packing flow per chapter (`_pack_chapter_sync`):

1. Create the series directory if missing.
2. Enumerate the chapter directory fresh — gallery-dl may have rewritten an
   extension between `handle_url` and download completion (e.g. `.png` URL
   serving JPEG bytes), so the path captured at record time can be stale.
3. Build `ComicInfo.xml` (`Series`, `Title`, `Number`, `Volume`, `Writer`,
   `Penciller`, `LanguageISO`, `Year/Month/Day`, `PageCount`, `Manga=Yes`).
   Series-level publication status is **not** part of the ComicInfo schema;
   it lives in the per-series `series.json` instead (see below).
4. Write `<target>.cbz.part`, then `.replace(target)` for atomicity.
5. If `delete_raw_after_pack` (from `app_config`, default `True`): guard
   that `ch.dir` is under `downloads_dir`, then `shutil.rmtree(ch.dir)`.

`run(...)` aggregates `PostResult(total, succeeded, failed, error_summary)`.
On any per-chapter exception the rest of the chapters still try; the
summary stitches the first 5 failure messages with `; (+N more)`.

### Series metadata (series.json)

Each pack pass writes (or refreshes) `<series_dir>/series.json` in the
Mylar-style format Komga imports natively. The payload is built by
`build_series_json_bytes(meta, total_issues)` from a `SeriesMetadata` derived
in three layers:

1. **Extractor-derived** — `derive_series_metadata` folds the first non-empty
   value seen across the chapter records (description, author, artist,
   language, year, publication status).
2. **Target overrides** — `Worker._series_metadata_overrides` reads the
   target's `tags`, `reading_direction`, and `series_status`; these win over
   the chapter-level values.
3. **Sim-pass auto-detect** — when the extractor exposed a
   Komga-recognised `status` string, `Worker._extract_manifest` already
   persisted it to `targets.series_status` (only when blank, never
   overwriting a user PATCH), so on the next pack it shows up in step 2.

Status normalisation (`normalize_series_status`) collapses provider
spellings — mangadex's `ongoing`, kaliscan's `Publishing`, manganelo's
`Completed`, etc. — to the four labels Komga reads verbatim: `Ongoing`,
`Ended`, `Hiatus`, `Abandoned`. Anything outside that set drops to an empty
string, which omits the `status` key from the on-disk JSON rather than
emitting noise Komga would ignore.

### Maintenance regen (`regenerate_series_metadata`)

The maintenance worker's regen job re-applies the same `derive_series_metadata`
+ ComicInfo plumbing to every existing CBZ on disk. It runs in two phases so
the per-series `series.json` lands **before** that series' per-chapter
ComicInfo.xml rewrites:

1. **Discovery** — walk each output root, read every CBZ's ComicInfo.xml,
   apply overrides + `chapter_date_for` lookup, and group the resulting
   `ChapterRecord`s by series directory. Nothing on disk changes yet.
2. **Per-series write** — for each discovered series directory:
   1. Build the `SeriesMetadata` from the chapter list + overrides and write
      `<series_dir>/series.json` atomically.
   2. Rewrite every CBZ in the directory (atomic `.part` rename, page bytes
      copied verbatim, only `ComicInfo.xml` replaced).

Komga's library scanner mtime-watches `series.json` — landing the series
file first means each `ComicInfo.xml` change that follows is imported against
fresh series-level metadata rather than the stale prior version. A failure
to write `series.json` for one series does not abort the chapter rewrites
under it: stale per-chapter metadata is worse than a partial success.

## Progress accounting

`downloads/progress.py` + `downloads/live_progress.py`

Per-chapter `stage`:

- `downloading` — at least one expected file is still missing.
- `processing` — all files present but the chapter hasn't been packed yet
  (or the whole job's postprocess is mid-flight).
- `completed` — packed (CBZ exists OR chapter dir gone after delete_raw) OR
  the job has settled with postprocess in a terminal state.

The progress route fuses two information sources:

- **Manifest** (`download_files`) — the list of expected relpaths from the
  simulation pass, persisted to SQLite.
- **Live state** — for an in-flight download, `LiveProgress.snapshot(id)`
  returns the in-memory list of relpaths the worker callback has recorded.
  Used in preference to the filesystem scan: avoids stat-storming the disk
  while the download is hot.

For already-settled jobs, `chapter_progress(...)` scans the chapter dirs on
disk. Stem (not full filename) matching is used because the simulation
pass may predict `.jpg` while the real download writes `.png` once the
extractor sees the response headers.

`stem`-level matching means progress only counts a file as "present" if its
name (without extension) appears in both the manifest and the directory —
the simplest invariant that survives extension churn.
