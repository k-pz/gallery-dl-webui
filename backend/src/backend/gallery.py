import logging
import os
from pathlib import Path
from typing import Any

from gallery_dl import config, extractor, output
from gallery_dl.job import DownloadJob, SimulationJob

from backend.settings import Settings


class _ManifestSimulationJob(SimulationJob):
    """SimulationJob variant that records every would-be file path.

    Child jobs spawned for nested extractors share the same _manifest list so a
    single run accumulates all expected paths.
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


class Gallery:
    """Thin wrapper around gallery-dl, scoped to one Settings instance.

    Configures gallery-dl's global state on construction. Constructing more
    than one instance per process is supported but will overwrite the previous
    configuration.
    """

    _configured = False

    def __init__(self, settings: Settings) -> None:
        self._downloads_dir = settings.downloads_dir
        if not Gallery._configured:
            output.initialize_logging(logging.INFO)
            Gallery._configured = True
        config.set(("extractor",), "base-directory", str(settings.downloads_dir))
        config.set(("extractor",), "archive", str(settings.archive_db_path))

    @property
    def downloads_dir(self) -> Path:
        return self._downloads_dir

    @staticmethod
    def find_extractor(url: str) -> str | None:
        try:
            found = extractor.find(url)
        except Exception:
            return None
        if found is None:
            return None
        return getattr(found, "category", None)

    def extract_manifest(self, url: str) -> list[str]:
        """Run gallery-dl in simulate mode; return expected files as paths
        relative to the configured downloads directory."""
        job = _ManifestSimulationJob(url)
        job.run()
        base = str(self._downloads_dir).rstrip(os.sep) + os.sep
        out: list[str] = []
        for full in job._manifest:
            out.append(full[len(base) :] if full.startswith(base) else full)
        return out

    @staticmethod
    def run_download(url: str) -> int:
        return DownloadJob(url).run()
