"""Cached per-series figures read from disk for the library list.

Counting a series' packed chapters and working out which of its EPUB books
still need exporting means scanning its directory. Doing that for every
series on each library refresh would be slow on a NAS, so the figures are
stored in `series_stats` and refreshed in the background when something
that affects them changes.
"""
