from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# downloading: chapter has not been observed in the live record stream yet.
# downloaded: at least one file has landed in a chapter directory, but
#             postprocess has not packed it yet.
# processing: all expected chapters have started downloading and postprocess
#             is actively running.
# completed:  the whole job (download + postprocess, if applicable) has
#             settled.
ChapterStage = Literal["downloading", "downloaded", "processing", "completed"]


@dataclass(frozen=True)
class ChapterProgress:
    name: str
    files_total: int
    files_present: int
    stage: ChapterStage


_TERMINAL_DOWNLOAD_STATUSES = {"completed", "failed", "cancelled"}
_TERMINAL_POSTPROCESS_STATUSES = {"completed", "skipped", "failed"}


def _settled(download_status: str, postprocess_status: str | None) -> bool:
    return download_status in _TERMINAL_DOWNLOAD_STATUSES and (
        postprocess_status is None or postprocess_status in _TERMINAL_POSTPROCESS_STATUSES
    )


def _unique_chapter_dirs(file_relpaths: list[str]) -> int:
    return len({str(Path(rel).parent) for rel in file_relpaths})


def chapter_progress(
    chapter_names: list[str],
    downloads_dir: Path,
    download_status: str = "running",
    postprocess_status: str | None = None,
) -> list[ChapterProgress]:
    """Settle-time progress: no live record stream, so per-chapter completion
    state is inferred from the overall job status.

    `downloads_dir` is unused (kept for API compatibility) — without the live
    record stream we can't map a chapter back to its on-disk directory.
    """
    del downloads_dir
    settled = _settled(download_status, postprocess_status)
    stage: ChapterStage = "completed" if settled else "downloading"
    present = 1 if settled else 0
    return [
        ChapterProgress(name=name, files_total=1, files_present=present, stage=stage)
        for name in chapter_names
    ]


def chapter_progress_from_completed(
    chapter_names: list[str],
    completed: list[str],
    download_status: str = "running",
    postprocess_status: str | None = None,
) -> list[ChapterProgress]:
    """Live-time progress: count unique chapter directories observed in the
    record stream and mark the first N rows as downloaded (order-based).

    Gallery-dl downloads chapter-by-chapter, so "N unique chapter directories
    have received at least one file" maps cleanly to "the first N rows in our
    chapter manifest are at least started". The last started chapter is
    technically mid-flight, but `downloaded` is the closest stage label and
    flips to `completed` once the job settles.
    """
    settled = _settled(download_status, postprocess_status)
    completed_count = _unique_chapter_dirs(completed)
    out: list[ChapterProgress] = []
    for i, name in enumerate(chapter_names):
        if settled:
            stage: ChapterStage = "completed"
            present = 1
        elif i < completed_count:
            present = 1
            if postprocess_status == "running":
                stage = "processing"
            else:
                stage = "downloaded"
        else:
            present = 0
            stage = "downloading"
        out.append(ChapterProgress(name=name, files_total=1, files_present=present, stage=stage))
    return out


def count_present_chapters(records_paths: list[Path]) -> int:
    """Count unique chapter directories represented in a list of file paths.

    Used by the worker to derive `files_downloaded` (now: chapters downloaded)
    from the FileRecords returned by a real download run, or from the live
    snapshot when a download fails mid-flight.
    """
    return len({str(p.parent) for p in records_paths})
