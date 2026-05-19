from datetime import timedelta

import pytest

from backend.targets.utils import format_duration, parse_duration


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
        ("1w", timedelta(weeks=1)),
        ("2h30m", timedelta(hours=2, minutes=30)),
        ("1w2d3h", timedelta(weeks=1, days=2, hours=3)),
        (" 1d ", timedelta(days=1)),
        ("1D", timedelta(days=1)),
    ],
)
def test_parse_duration_accepts_valid(raw: str, expected: timedelta) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "60", "1y", "1x", "h1", "-1h", "0s", "0m0s"])
def test_parse_duration_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_format_duration_compacts_units() -> None:
    assert format_duration(timedelta(seconds=90)) == "1m30s"
    assert format_duration(timedelta(days=1, hours=2)) == "1d2h"
    assert format_duration(timedelta(weeks=2, days=3)) == "2w3d"


def test_format_duration_zero() -> None:
    assert format_duration(timedelta(0)) == "0s"
