from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# downloading: at least one expected file is still missing on disk / in-memory.
# downloaded: all files are present, but postprocess has not started yet.
# processing: all files are present and postprocess is actively running.
# completed:   the chapter has been packed (CBZ exists or chapter dir gone after
#              delete_raw) OR the whole job's postprocess has finished.
ChapterStage = Literal["downloading", "downloaded", "processing", "completed"]


@dataclass(frozen=True)
class ChapterProgress:
    name: str
    files_total: int
    files_present: int
    stage: ChapterStage


def _group_stems_by_dir(relpaths: list[str]) -> OrderedDict[Path, list[str]]:
    """Group manifest relpaths into expected stems per parent directory.

    Stems (not full filenames) are used because SimulationJob may predict an
    extension (e.g. ".jpg") that differs from what the real download writes
    (".png") — extractors only learn the real type from response headers.
    """
    groups: OrderedDict[Path, list[str]] = OrderedDict()
    for rel in relpaths:
        p = Path(rel)
        groups.setdefault(p.parent, []).append(p.stem)
    return groups


def _present_stems_in(directory: Path) -> set[str]:
    try:
        return {child.stem for child in directory.iterdir() if child.is_file()}
    except FileNotFoundError:
        return set()


_TERMINAL_DOWNLOAD_STATUSES = {"completed", "failed", "cancelled"}
_TERMINAL_POSTPROCESS_STATUSES = {"completed", "skipped", "failed"}


def _stage_for(
    files_present: int,
    files_total: int,
    dir_existed: bool,
    download_status: str,
    postprocess_status: str | None,
) -> ChapterStage:
    """Derive a per-chapter stage from the available signals.

    Once the whole job has settled — the download is terminal AND post-process
    (when applicable) has reached its own terminal state — every chapter that
    had any expected files is reported as completed. While post-process is
    still running, we infer per-chapter completion from the absence of the
    chapter directory (delete_raw removes it post-pack).
    """
    settled = (
        download_status in _TERMINAL_DOWNLOAD_STATUSES
        and (postprocess_status is None or postprocess_status in _TERMINAL_POSTPROCESS_STATUSES)
    )
    if settled and files_total > 0:
        return "completed"
    if files_total > 0 and not dir_existed:
        return "completed"
    if files_total > 0 and files_present >= files_total:
        if postprocess_status == "running":
            return "processing"
        return "downloaded"
    return "downloading"


def chapter_progress(
    relpaths: list[str],
    downloads_dir: Path,
    download_status: str = "running",
    postprocess_status: str | None = None,
) -> list[ChapterProgress]:
    out: list[ChapterProgress] = []
    for parent, expected in _group_stems_by_dir(relpaths).items():
        dir_path = downloads_dir / parent
        dir_existed = dir_path.exists()
        present_set = _present_stems_in(dir_path) if dir_existed else set()
        present = sum(1 for s in expected if s in present_set)
        name = parent.name if str(parent) != "." else ""
        out.append(
            ChapterProgress(
                name=name,
                files_total=len(expected),
                files_present=present,
                stage=_stage_for(
                    present, len(expected), dir_existed, download_status, postprocess_status
                ),
            )
        )
    return out


def count_present(relpaths: list[str], downloads_dir: Path) -> int:
    return sum(c.files_present for c in chapter_progress(relpaths, downloads_dir))


def chapter_progress_from_completed(
    relpaths: list[str],
    completed: list[str],
    download_status: str = "running",
    postprocess_status: str | None = None,
) -> list[ChapterProgress]:
    """Like chapter_progress, but counts matches against an in-memory set of
    completed relpaths instead of scanning the filesystem. Stem matching is
    preserved so a real-extension/simulated-extension mismatch still resolves.

    The in-memory snapshot is only used while the download is live, so dir
    existence is implied (true) and the stage never reports "completed" from
    the disk signal — that path is only reached via `postprocess_status`.
    """
    completed_by_dir: dict[Path, set[str]] = {}
    for rel in completed:
        p = Path(rel)
        completed_by_dir.setdefault(p.parent, set()).add(p.stem)
    out: list[ChapterProgress] = []
    for parent, expected in _group_stems_by_dir(relpaths).items():
        present_set = completed_by_dir.get(parent, set())
        present = sum(1 for s in expected if s in present_set)
        name = parent.name if str(parent) != "." else ""
        out.append(
            ChapterProgress(
                name=name,
                files_total=len(expected),
                files_present=present,
                stage=_stage_for(
                    present, len(expected), True, download_status, postprocess_status
                ),
            )
        )
    return out
