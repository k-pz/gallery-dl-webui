from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from gallery_dl import config, extractor, output
from gallery_dl.job import DownloadJob, SimulationJob

from settings import Settings

_configured = False
_downloads_dir: Path | None = None


class _ManifestSimulationJob(SimulationJob):
    """SimulationJob variant that records every would-be file path.

    Child jobs spawned for nested extractors share the same _manifest list so
    a single run accumulates all expected paths.
    """

    _manifest: list[str]

    def __init__(self, url: Any, parent: SimulationJob | None = None) -> None:
        super().__init__(url, parent)
        if isinstance(parent, _ManifestSimulationJob):
            self._manifest = parent._manifest
        else:
            self._manifest = []

    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        # SimulationJob.handle_directory only calls initialize() and never sets
        # pathfmt.directory, so the recorded paths would be missing the per-job
        # directory prefix. Mirror DownloadJob.handle_directory's behavior.
        if self.pathfmt is None:
            self.initialize(kwdict)
        else:
            self.pathfmt.set_directory(kwdict)

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        pathfmt = self.pathfmt
        assert pathfmt is not None
        ext = kwdict["extension"] or "jpg"
        kwdict["extension"] = pathfmt.extension_map(ext, ext)
        if self.archive is not None and self._archive_write_skip:
            self.archive.add(kwdict)
        filename = pathfmt.build_filename(kwdict)
        self._manifest.append(pathfmt.directory + filename)


def configure(settings: Settings) -> None:
    global _configured, _downloads_dir
    _downloads_dir = settings.downloads_dir
    if _configured:
        return
    output.initialize_logging(logging.INFO)
    config.set(("extractor",), "base-directory", str(settings.downloads_dir))
    config.set(("extractor",), "archive", str(settings.archive_db_path))
    _configured = True


def find_extractor(url: str) -> str | None:
    try:
        found = extractor.find(url)
    except Exception:
        return None
    if found is None:
        return None
    return getattr(found, "category", None)


def extract_manifest(url: str) -> list[str]:
    """Run gallery-dl in simulate mode and return the expected files as paths
    relative to the configured downloads directory."""
    if _downloads_dir is None:
        raise RuntimeError("gallery_runtime.configure() must be called first")
    job = _ManifestSimulationJob(url)
    job.run()
    base = str(_downloads_dir).rstrip(os.sep) + os.sep
    out: list[str] = []
    for full in job._manifest:
        if full.startswith(base):
            out.append(full[len(base) :])
        else:
            out.append(full)
    return out


def run_download(url: str) -> int:
    job = DownloadJob(url)
    return job.run()


def _stems_by_dir(relpaths: list[str]) -> dict[Path, set[str]]:
    """Group manifest relpaths into expected stems per parent directory.

    Stem-based matching is necessary because SimulationJob may predict an
    extension (e.g. ".jpg") that differs from what the real download writes
    (".png") — extractors only learn the real type from response headers.
    """
    out: dict[Path, set[str]] = {}
    for rel in relpaths:
        p = Path(rel)
        out.setdefault(p.parent, set()).add(p.stem)
    return out


def _present_stems_in(directory: Path) -> set[str]:
    try:
        return {child.stem for child in directory.iterdir() if child.is_file()}
    except FileNotFoundError:
        return set()


def count_present(relpaths: list[str]) -> int:
    if _downloads_dir is None:
        raise RuntimeError("gallery_runtime.configure() must be called first")
    base = _downloads_dir
    total = 0
    for parent, expected_stems in _stems_by_dir(relpaths).items():
        present = _present_stems_in(base / parent)
        total += sum(1 for s in expected_stems if s in present)
    return total
