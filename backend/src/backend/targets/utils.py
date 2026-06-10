"""Human-readable durations.

Accept compact specs like `30s`, `5m`, `2h`, `1d`, `1w`, `2h30m`, `1w2d3h`.
Whitespace between parts is tolerated. Bare numbers without a unit are
rejected — `60` is ambiguous (seconds? minutes?).
"""

from __future__ import annotations

import re
from datetime import timedelta

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_FULL = re.compile(r"^\s*(?:\d+\s*[smhdw]\s*)+$", re.IGNORECASE)
_DURATION_PART = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)


def parse_duration(raw: str) -> timedelta:
    if not raw or not _DURATION_FULL.match(raw):
        raise ValueError(f"invalid duration: {raw!r} (use e.g. '30m', '2h', '1d')")
    total = 0
    for n, unit in _DURATION_PART.findall(raw):
        total += int(n) * _UNIT_SECONDS[unit.lower()]
    if total <= 0:
        raise ValueError(f"duration must be > 0: {raw!r}")
    return timedelta(seconds=total)
