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


def parse_duration(raw: str) -> timedelta:
    invalid = ValueError(f"invalid duration: {raw!r} (use e.g. '30m', '2h', '1d')")
    if not raw or not _DURATION_FULL.match(raw):
        raise invalid
    # The anchored shape check above guarantees "<digits> <unit>" parts
    # separated by whitespace, so one left-to-right scan extracts them. An
    # unanchored `findall(r"(\d+)\s*([smhdw])")` would backtrack quadratically
    # on long digit runs (it restarts the `\d+` scan at every digit).
    total = 0
    digits = ""
    for ch in raw:
        if ch.isdecimal():
            digits += ch
        elif not ch.isspace():
            # IGNORECASE also lets case-folding lookalikes (U+017F long s for "s")
            # through the shape check; they are not units.
            unit = _UNIT_SECONDS.get(ch.lower())
            if unit is None or not digits:
                raise invalid
            total += int(digits) * unit
            digits = ""
    if total <= 0:
        raise ValueError(f"duration must be > 0: {raw!r}")
    return timedelta(seconds=total)
