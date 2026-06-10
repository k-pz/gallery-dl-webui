from backend.downloads.worker import _ProgressEventThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_first_call_always_passes() -> None:
    throttle = _ProgressEventThrottle(interval_s=1.0, clock=FakeClock())
    assert throttle.ready() is True


def test_calls_within_interval_are_suppressed() -> None:
    clock = FakeClock()
    throttle = _ProgressEventThrottle(interval_s=1.0, clock=clock)
    assert throttle.ready() is True
    clock.now = 0.2
    assert throttle.ready() is False
    clock.now = 0.999
    assert throttle.ready() is False


def test_call_after_interval_passes_and_rearms() -> None:
    clock = FakeClock()
    throttle = _ProgressEventThrottle(interval_s=1.0, clock=clock)
    assert throttle.ready() is True
    clock.now = 1.0
    assert throttle.ready() is True
    # The window restarts from the last accepted call, not from t=0.
    clock.now = 1.5
    assert throttle.ready() is False
    clock.now = 2.0
    assert throttle.ready() is True
