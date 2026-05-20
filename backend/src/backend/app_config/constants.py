from __future__ import annotations

DEFAULT_DELETE_RAW = True
DEFAULT_WATCH_PERIOD = "1d"
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
