from backend.live_progress import LiveProgress


def test_snapshot_returns_none_when_not_started() -> None:
    live = LiveProgress()
    assert live.snapshot(1) is None


def test_record_after_start_collects_relpaths() -> None:
    live = LiveProgress()
    live.start(1)
    live.record(1, "ch1/001.jpg")
    live.record(1, "ch1/002.jpg")

    assert live.snapshot(1) == ["ch1/001.jpg", "ch1/002.jpg"]


def test_record_without_start_is_dropped() -> None:
    live = LiveProgress()
    live.record(7, "ch1/001.jpg")
    assert live.snapshot(7) is None


def test_snapshot_returns_a_copy() -> None:
    live = LiveProgress()
    live.start(1)
    live.record(1, "a")
    snap = live.snapshot(1)
    assert snap == ["a"]
    snap.append("b")
    assert live.snapshot(1) == ["a"]


def test_clear_removes_state() -> None:
    live = LiveProgress()
    live.start(1)
    live.record(1, "a")
    live.clear(1)
    assert live.snapshot(1) is None


def test_clear_unknown_id_is_safe() -> None:
    live = LiveProgress()
    live.clear(999)


def test_isolation_between_downloads() -> None:
    live = LiveProgress()
    live.start(1)
    live.start(2)
    live.record(1, "a")
    live.record(2, "b")
    assert live.snapshot(1) == ["a"]
    assert live.snapshot(2) == ["b"]
