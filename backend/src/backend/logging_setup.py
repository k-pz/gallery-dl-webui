"""Centralised logging config.

Called once at app startup. Defaults to DEBUG so journalctl captures the full
trace of what the workers, poller and request handlers are doing; override
with the `LOG_LEVEL` env var when that's too noisy. A few third-party loggers
are clamped to INFO/WARNING so their internal chatter doesn't drown out our
own debug lines.
"""

from __future__ import annotations

import logging
import os

_THIRD_PARTY_QUIET = {
    # uvicorn.access prints one line per request at INFO; that's fine, but
    # debug-level chatter from inside the ASGI plumbing is overkill.
    "uvicorn.error": "INFO",
    "uvicorn.asgi": "INFO",
    "watchfiles": "WARNING",
    "asyncio": "INFO",
    "aiosqlite": "INFO",
    "httpcore": "INFO",
    "httpx": "INFO",
    "PIL": "INFO",
}


def configure_logging() -> int:
    """Install a verbose default config. Returns the resolved root level."""
    raw = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    level = logging.getLevelNamesMapping().get(raw, logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    # Replace existing handlers — uvicorn or pytest may have installed their
    # own; we want a single consistent format reaching journalctl.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    # Our own package follows the root level explicitly so external imports
    # raising the root threshold later don't accidentally silence us.
    logging.getLogger("backend").setLevel(level)

    for name, cap in _THIRD_PARTY_QUIET.items():
        cap_level = logging.getLevelNamesMapping().get(cap, logging.INFO)
        logging.getLogger(name).setLevel(max(level, cap_level))

    return level
