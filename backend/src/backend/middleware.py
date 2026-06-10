"""Request-scoped event collection: forward events to the mutating client via
the `X-Events` response header so its TanStack Query cache can invalidate
synchronously, without a websocket roundtrip.

The websocket layer (`realtime.router`) keeps delivering the same events to
every connected client, including the mutating one, so a tab that doesn't
read its own response header (and other tabs) stay in sync. The mutating
client receives the event twice in normal operation — TanStack
`invalidateQueries` is idempotent, so this is fine.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from backend.events import close_request_event_buffer, open_request_event_buffer

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

# Browsers cap response header size around 8 KB. A single event serialises
# to ~80 bytes, so this is a generous ceiling. If a single request emits
# more than this we drop the header rather than risk a malformed response;
# the websocket path will still deliver the events.
_MAX_HEADER_BYTES = 6 * 1024
_HEADER_NAME = "X-Events"


async def request_event_collector_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Open a request-scoped event buffer; serialise it into the response.

    Anything `EventBus.publish` emits during the request lands in this
    buffer (in addition to fanning out to websocket subscribers). On the
    way out, the collected events become the `X-Events` header.
    """
    buf, token = open_request_event_buffer()
    try:
        response = await call_next(request)
    finally:
        close_request_event_buffer(token)
    if buf:
        payload = json.dumps([e.to_json() for e in buf], separators=(",", ":"))
        if len(payload.encode("utf-8")) <= _MAX_HEADER_BYTES:
            response.headers[_HEADER_NAME] = payload
        else:
            logger.debug(
                "skipping %s header: payload %d bytes > %d",
                _HEADER_NAME,
                len(payload),
                _MAX_HEADER_BYTES,
            )
    return response
