from __future__ import annotations

from pydantic import BaseModel


class AppConfigOut(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    postprocess_known_output_dirs: list[str]
    postprocess_excluded_dir_names: list[str]
    delete_raw_after_pack: bool
    default_watch_period: str
    chapter_naming_template: str
    default_reading_direction: str
    max_parallel_postprocess: int
    komga_base_url: str | None
    komga_api_key: str | None
    # Where EPUB exports are written; None means the default
    # `<data dir>/epub` (see `epub_export_dir_default`).
    epub_export_dir: str | None = None
    epub_export_dir_default: str = ""


class AppConfigIn(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    delete_raw_after_pack: bool
    default_watch_period: str | None = None
    chapter_naming_template: str | None = None
    default_reading_direction: str | None = None
    postprocess_excluded_dir_names: list[str] | None = None
    max_parallel_postprocess: int | None = None
    komga_base_url: str | None = None
    komga_api_key: str | None = None
    # Omitted preserves the stored value; null or blank resets to the default.
    epub_export_dir: str | None = None
