from datetime import timedelta

import pytest

from backend.targets.utils import parse_duration


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


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1w 2d\t3h  4m 5s", timedelta(weeks=1, days=2, hours=3, minutes=4, seconds=5)),
        ("90 M", timedelta(minutes=90)),
        ("007h", timedelta(hours=7)),
    ],
)
def test_parse_duration_handles_spacing_case_and_padding(raw: str, expected: timedelta) -> None:
    assert parse_duration(raw) == expected


def test_parse_duration_rejects_case_folded_unit_lookalikes() -> None:
    # U+017F (long s) case-folds to "s", so the case-insensitive shape check
    # accepts it; it must still be rejected as invalid, not crash.
    with pytest.raises(ValueError):
        parse_duration("1\u017f")


def test_parse_duration_long_digit_runs_stay_linear() -> None:
    # A unit-less digit run must be rejected without quadratic backtracking.
    with pytest.raises(ValueError):
        parse_duration("9" * 200_000)
    assert parse_duration("1s" * 50_000) == timedelta(seconds=50_000)
