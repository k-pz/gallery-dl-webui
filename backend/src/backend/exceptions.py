"""Base exception types used by domain modules.

Each domain raises HTTPException subclasses with a fixed status/detail so the
route handlers don't repeat the same `raise HTTPException(404, ...)` boilerplate.
Per the FastAPI best-practices guide, custom exceptions are how we centralise
error wording and status codes.
"""

from __future__ import annotations

from fastapi import HTTPException


class WebUIError(HTTPException):
    """Base class for all domain-specific HTTP errors raised by routes."""

    status_code: int = 500
    detail: str = "internal error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(status_code=self.status_code, detail=detail or self.detail)


class NotFoundError(WebUIError):
    status_code = 404
    detail = "resource not found"


class ConflictError(WebUIError):
    status_code = 409
    detail = "conflict"


class BadRequestError(WebUIError):
    status_code = 400
    detail = "bad request"
