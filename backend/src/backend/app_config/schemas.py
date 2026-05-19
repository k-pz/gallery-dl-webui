from __future__ import annotations

from pydantic import BaseModel


class AppConfigOut(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    postprocess_known_output_dirs: list[str]
    delete_raw_after_pack: bool
    default_watch_period: str


class AppConfigIn(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    delete_raw_after_pack: bool
    default_watch_period: str | None = None
