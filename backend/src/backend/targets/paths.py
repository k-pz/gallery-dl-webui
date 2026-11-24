"""Where a target's packed chapters live on disk."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from backend.comic_metadata import sanitize
from backend.targets.schemas import Target


def target_series_dir(target: Target, cfg: Mapping[str, object]) -> Path | None:
    """The directory the packer writes this series' CBZs into:
    `<output dir>/<sanitized series name>`, where the output dir is the
    target's own or the configured default. None until the series has a
    name and an output dir is known."""
    default_out = cfg.get("postprocess_default_output_dir")
    output_dir = target.output_dir or (default_out if isinstance(default_out, str) else None)
    if not output_dir or not target.name:
        return None
    return Path(output_dir) / sanitize(target.name)
