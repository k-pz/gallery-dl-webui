# Lifecycles end-to-end

Traces of the data + control flow for each user-visible operation. Each
section follows one request from the UI all the way through to a row in
SQLite and (where relevant) files on disk.

The components referenced here are documented in
[Backend](backend.md) and [Download pipeline](pipeline.md).

## Single download

```
user types URL → SubmitForm.mutate
  → POST /api/downloads { url, output_dir? }
    └── router.create_download
         ├── Gallery.find_extractor → 400 if no match
         ├── validate_under_root + remember_output_dir   (if output_dir set)
         ├── targets_service.upsert(url, extractor, output_dir)
         ├── downloads_service.insert_pending → status=pending
         └── worker.notify()  ◄── wakes Worker._wakeup event

Worker loop wakes
  └── claim_next_pending → status=extracting, started_at=now
       └── _process(job)
            ├── _build_skip_chapter   (watched targets only)
            ├── _extract_manifest   (gallery-dl SimulationJob, asyncio.to_thread)
            │     → save_manifest, set targets.name (if discovered)
            ├── mark_running → status=running
            ├── live.start(id)
            ├── run_download (asyncio.to_thread)
            │     callbacks → live.record(id, relpath)
            │     cancel? → StopExtraction → exits cleanly
            ├── count_present → finish_job(exit_code, present)
            │                   OR mark_cancelled(present)
            ├── live.clear(id)
            └── if exit==0 and not cancelled:
                   _run_postprocess
                     ├── mark_postprocess(running)
                     ├── postprocess.run → CBZs under <output_dir>/<Series>/
                     └── mark_postprocess(completed/failed)
```

While this runs, the UI is polling `GET /api/downloads/{id}` (1 s) and
`GET /api/downloads/{id}/progress` (1 s); both endpoints self-disable in
the client once the row is terminal.

## Watched-target re-poll

```
Poller wakes (every 30 s, or .notify())
  └── _tick_once
       ├── load default_watch_period from app_config
       ├── list_watched
       └── for each target:
            ├── is_due(target, default_period, now)?
            ├── has_active_for_target(id)?  ── skip if yes
            ├── downloads_service.insert_pending(url, extractor, output_dir, target_id)
            └── mark_polled
       └── if anything queued: worker.notify()

→ Worker picks it up from `pending`, same flow as a manual submit
→ skip_chapter predicate avoids re-downloading chapters that already
  exist as CBZs under the output dir.
```

## Cancel

```
UI clicks Cancel
  → cancelMutation.mark()    ─── (optimistic flag → "Cancelling…")
  → POST /api/downloads/{id}/cancel
    └── router.cancel_download
         ├── 409 if status in TERMINAL_STATUSES
         ├── worker.request_cancel(id)   ── sets bool if it's the current job
         └── service.cancel_pending(id)  ── flips status=cancelled if still pending

If the job was running:
  worker's per-file callback observes _cancel_requested
   └── raises StopExtraction
        └── gallery-dl unwinds, run_download returns
             └── service.mark_cancelled(id, present)
```

## Boot recovery

If the process is killed while a download is running, the row stays in
`extracting`/`running` until the next start. `mark_interrupted_on_boot` in
`lifespan` flips every such row to `failed` with
`error = "interrupted: backend restarted"`. Logged as a warning. The user
can `Requeue` from the UI.
