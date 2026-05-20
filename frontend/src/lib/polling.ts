// Fallback polling intervals. The websocket event stream
// (`useEventStream`) keeps the cache fresh under normal operation; these
// timeouts only matter if the socket has been disconnected. They're
// intentionally slack — the UI catches up the moment the socket comes back.
export const REFETCH_ACTIVE_MS = 5000;
export const REFETCH_LIST_MS = 10000;
