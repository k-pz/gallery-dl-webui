---
title: backend.database
---

# `backend.database`

`aiosqlite` connection lifecycle, schema bootstrap, and forward-only
migrations. A single shared connection is held on `app.state.db` for the
process lifetime.

::: backend.database
