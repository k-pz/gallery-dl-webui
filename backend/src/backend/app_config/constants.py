from __future__ import annotations

DEFAULT_DELETE_RAW = True
DEFAULT_WATCH_PERIOD = "1d"
# Directory names that maintenance + output-dir scans should always skip,
# matched anywhere in the path. Synology shares hide their recycle bin under
# `#recycle/`; NAS-mounted output trees pick up similar trash directories
# from time-machine, Dropbox, etc. The user can extend this via Config.
DEFAULT_EXCLUDED_DIR_NAMES: tuple[str, ...] = ("#recycle", "@eaDir", ".Trash", ".Trashes")
DEFAULT_CHAPTER_NAMING_TEMPLATE = (
    "{{ series }} - c{{ chapter_number }}{% if title %} - {{ title }}{% endif %}"
)
KNOWN_OUTPUT_DIRS_LIMIT = 20

# Komga reads only LTR vs RTL from ComicInfo's `Manga` element; vertical and
# webtoon are passed through to series.json so downstream tooling (or a manual
# Komga setting) can pick them up. Keep the literal set in sync with the
# frontend dropdown.
READING_DIRECTIONS = ("ltr", "rtl", "vertical", "webtoon")
DEFAULT_READING_DIRECTION = "ltr"

# How many gallery-dl simulation/download passes run in parallel. Two is a
# conservative default: it doubles throughput for queue-heavy sessions while
# keeping the load on the gallery-dl archive.db and the remote extractor
# polite. The hard ceiling at construction time is 16.
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 2
# Parallel CBZ packing inside one job's postprocess pass. zipfile releases the
# GIL during deflate, so a small handful of threads is enough to overlap
# packing with shutil.rmtree on the previous chapter.
DEFAULT_MAX_PARALLEL_POSTPROCESS = 3
