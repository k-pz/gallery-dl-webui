from __future__ import annotations

from backend.exceptions import BadRequestError


class PostprocessRootNotConfigured(BadRequestError):
    """Raised when an operation requires postprocess_root but it is unset."""

    def __init__(self, field: str = "operation") -> None:
        super().__init__(f"{field} requires postprocess_root to be configured")


class DefaultOutputDirWithoutRoot(BadRequestError):
    detail = "postprocess_default_output_dir requires postprocess_root"
