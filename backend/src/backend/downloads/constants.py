"""Status taxonomy for downloads.

A download moves through `pending → extracting → running → (completed | failed | cancelled)`.
Active means the worker is still touching it; terminal means it is settled.
"""

from __future__ import annotations

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATUSES: frozenset[str] = frozenset({"pending", "extracting", "running"})
