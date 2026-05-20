# Testing

## Backend

`pytest`, `pytest-asyncio` (auto mode). Test layout mirrors `src/`:

```
tests/
  conftest.py                  ← TestClient fixture wiring create_app(...) to FakeGallery
  fakes.py                     ← FakeGallery + FakeGalleryConfig
  e2e_server.py                ← ASGI app for Playwright
  test_database.py             ← schema/migration coverage
  test_config.py               ← Settings env parsing
  <domain>/test_router.py      ← full-stack HTTP via TestClient
  <domain>/test_service.py     ← service-layer SQL
  downloads/test_worker.py     ← worker lifecycle, cancellation, postprocess
  downloads/test_postprocess.py
  downloads/test_progress.py / test_live_progress.py
  targets/test_poller.py
  targets/test_utils.py        ← parse_duration / format_duration
```

`FakeGallery` (in `tests/fakes.py`) lets tests configure per-URL manifests,
records, and series names without ever touching gallery-dl. It honours the
`skip_chapter` predicate and the `on_file_complete` / `StopExtraction`
contract so cancellation paths can be exercised.

## Frontend

- **Vitest** (`pnpm test` / `mise run test:frontend`) — jsdom + Testing
  Library for components, plain `describe/it` for `lib/` helpers. Setup in
  `src/test/setup.ts`.
- **Playwright** (`pnpm test:e2e`) — boots the real React app against the
  `FakeGallery`-backed backend. Useful smoke for the submit → progress →
  completion path.
