from backend.maintenance.live_progress import MaintenanceLiveProgress


def test_snapshot_returns_none_when_not_started() -> None:
    live = MaintenanceLiveProgress()
    assert live.snapshot(1) is None


def test_record_and_counts_after_start() -> None:
    live = MaintenanceLiveProgress()
    live.start(1)
    live.set_total(1, 3)
    live.record(1, "scanning")
    live.increment_done(1)
    live.record(1, "renamed: a")
    snap = live.snapshot(1)
    assert snap is not None
    assert snap.total == 3
    assert snap.done == 1
    assert snap.lines == ["scanning", "renamed: a"]


def test_set_total_before_start_is_dropped() -> None:
    live = MaintenanceLiveProgress()
    live.set_total(2, 10)
    assert live.snapshot(2) is None


def test_tail_size_bounded() -> None:
    live = MaintenanceLiveProgress(tail_size=2)
    live.start(7)
    live.record(7, "a")
    live.record(7, "b")
    live.record(7, "c")
    snap = live.snapshot(7)
    assert snap is not None
    assert snap.lines == ["b", "c"]


def test_clear_removes_state() -> None:
    live = MaintenanceLiveProgress()
    live.start(1)
    live.record(1, "x")
    live.clear(1)
    assert live.snapshot(1) is None


def test_isolation_between_jobs() -> None:
    live = MaintenanceLiveProgress()
    live.start(1)
    live.start(2)
    live.record(1, "a")
    live.record(2, "b")
    snap1 = live.snapshot(1)
    snap2 = live.snapshot(2)
    assert snap1 is not None and snap1.lines == ["a"]
    assert snap2 is not None and snap2.lines == ["b"]
