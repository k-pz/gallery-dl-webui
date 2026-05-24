"""SSE endpoint that streams the systemd journal for the running service.

The endpoint shells out to `journalctl --follow --output=json` so we get every
priority the journal recorded — including DEBUG, which our `logging_setup`
defaults to. Each JSON line is reshaped into a small entry payload and pushed
to the browser as one SSE message. The unit name is pinned via the
`WEBUI_LOG_UNIT` env var (default `gallery-dl-webui`), never taken from the
request, so the query string can't smuggle in shell args.

On hosts without journalctl (dev macOS, containers without systemd) the
endpoint sends a single `error` event and closes — the UI shows that to the
user instead of silently failing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])

DEFAULT_LINES = 500
MAX_LINES = 50_000

# Syslog priority (PRIORITY field in journal JSON) → human level. We surface
# the bottom of the table so the UI can colour or filter on it.
_PRIORITY_NAMES = {
    0: "emerg",
    1: "alert",
    2: "crit",
    3: "error",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}


def _unit_name() -> str:
    return os.environ.get("WEBUI_LOG_UNIT", "gallery-dl-webui")


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Reshape a journalctl JSON record into the wire format the UI consumes."""
    pri_raw = raw.get("PRIORITY")
    try:
        pri = int(pri_raw) if pri_raw is not None else 6
    except TypeError, ValueError:
        pri = 6
    ts_us_raw = raw.get("__REALTIME_TIMESTAMP")
    try:
        # journald stores microseconds since epoch as a string.
        ts_ms = int(ts_us_raw) // 1000 if ts_us_raw is not None else None
    except TypeError, ValueError:
        ts_ms = None
    message = raw.get("MESSAGE")
    if isinstance(message, list):
        # Binary fields come back as a list of ints — render as best-effort utf-8.
        try:
            message = bytes(message).decode("utf-8", errors="replace")
        except TypeError, ValueError:
            message = str(message)
    elif message is None:
        message = ""
    else:
        message = str(message)
    return {
        "ts_ms": ts_ms,
        "priority": pri,
        "level": _PRIORITY_NAMES.get(pri, "info"),
        "message": message,
        "unit": raw.get("_SYSTEMD_UNIT") or raw.get("UNIT"),
        "ident": raw.get("SYSLOG_IDENTIFIER"),
        "pid": raw.get("_PID"),
    }


async def _stream(request: Request, lines: int) -> AsyncIterator[bytes]:
    unit = _unit_name()
    yield _sse("ready", {"unit": unit, "lines": lines})

    journalctl = shutil.which("journalctl")
    if journalctl is None:
        yield _sse(
            "error",
            {
                "message": (
                    "journalctl is not installed on this host — live log tail is "
                    "only available in production (systemd journal)."
                ),
            },
        )
        return

    cmd = [
        journalctl,
        "--no-pager",
        "--output=json",
        "--follow",
        "-n",
        str(lines),
        "-u",
        unit,
    ]
    logger.debug("starting journalctl tail: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        yield _sse("error", {"message": f"failed to start journalctl: {exc}"})
        return

    assert proc.stdout is not None
    try:
        while True:
            if await request.is_disconnected():
                logger.debug("client disconnected; terminating journalctl")
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=15.0)
            except TimeoutError:
                # Heartbeat keeps intermediaries from closing the idle stream.
                yield b": ping\n\n"
                continue
            if not line:
                # Subprocess exited.
                break
            try:
                raw = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                # journalctl --output=json should be one JSON object per line;
                # skip anything that isn't and continue.
                continue
            yield _sse("log", _normalize_entry(raw))
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
        if proc.returncode and proc.returncode != 0:
            stderr = b""
            if proc.stderr is not None:
                try:
                    stderr = await proc.stderr.read()
                except OSError, ValueError:
                    stderr = b""
            logger.warning(
                "journalctl exited with %s: %s",
                proc.returncode,
                stderr.decode("utf-8", errors="replace").strip(),
            )


@router.get("/logs/tail")
async def tail_logs(
    request: Request,
    lines: int = Query(default=DEFAULT_LINES, ge=1, le=MAX_LINES),
) -> StreamingResponse:
    """SSE stream of the running service's journal entries.

    The response is `text/event-stream`. Two event types are emitted:
    `ready` once at the start carrying `{unit, lines}`, then `log` per entry
    carrying `{ts_ms, priority, level, message, unit, ident, pid}`. A single
    `error` event is sent if the host doesn't have journalctl available.
    """
    return StreamingResponse(
        _stream(request, lines),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
