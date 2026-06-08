import logging
import threading

from backend.downloads.capture import ChapterErrorCollector


def _record(msg: str, level: int = logging.ERROR) -> logging.LogRecord:
    rec = logging.LogRecord("gallery-dl.test", level, __file__, 1, msg, None, None)
    rec.thread = threading.get_ident()
    return rec


def test_buckets_error_to_current_chapter() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("boom 403"))
    assert collector.errors == {"5": "boom 403"}


def test_keeps_first_error_per_chapter() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("first"))
    collector.emit(_record("second"))
    assert collector.errors["5"] == "first"


def test_ignores_records_with_no_current_chapter() -> None:
    ctx = [""]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("orphan"))
    assert collector.errors == {}


def test_ignores_records_from_other_threads() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, thread_id=-1)
    collector.emit(_record("from-this-thread"))
    assert collector.errors == {}
