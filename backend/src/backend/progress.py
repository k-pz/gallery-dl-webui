from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChapterProgress:
    name: str
    files_total: int
    files_present: int


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


def chapter_progress(relpaths: list[str], downloads_dir: Path) -> list[ChapterProgress]:
    out: list[ChapterProgress] = []
    for parent, expected in _group_stems_by_dir(relpaths).items():
        present_set = _present_stems_in(downloads_dir / parent)
        present = sum(1 for s in expected if s in present_set)
        name = parent.name if str(parent) != "." else ""
        out.append(ChapterProgress(name=name, files_total=len(expected), files_present=present))
    return out


def count_present(relpaths: list[str], downloads_dir: Path) -> int:
    return sum(c.files_present for c in chapter_progress(relpaths, downloads_dir))


def chapter_progress_from_completed(
    relpaths: list[str], completed: list[str]
) -> list[ChapterProgress]:
    """Like chapter_progress, but counts matches against an in-memory set of
    completed relpaths instead of scanning the filesystem. Stem matching is
    preserved so a real-extension/simulated-extension mismatch still resolves.
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
        out.append(ChapterProgress(name=name, files_total=len(expected), files_present=present))
    return out
