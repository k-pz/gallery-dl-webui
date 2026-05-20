from __future__ import annotations

DEFAULT_DELETE_RAW = True
DEFAULT_WATCH_PERIOD = "1d"
DEFAULT_CHAPTER_NAMING_TEMPLATE = (
    "{{ series }} - c{{ chapter_number }}{% if title %} - {{ title }}{% endif %}"
)
KNOWN_OUTPUT_DIRS_LIMIT = 20
