# Changelog

All notable changes to this project are recorded here. Entries are appended
by [Commitizen](https://commitizen-tools.github.io/commitizen/) when
`develop` is merged into `main` — see [`CONTRIBUTING.md`](CONTRIBUTING.md)
for the release flow.

## v1.1.0 (2026-05-25)

### Feat

- **release**: add mise run release:preview task

## v1.0.0 (2026-05-25)

### Feat

- **maintenance**: switch Komga sync to API-key config
- **frontend**: let maintenance job log expand on mobile
- **frontend**: sync active tab with the URL
- **jobs**: auto-open the current job and follow it as work advances
- **frontend**: consume X-Events response header for sync cache invalidation
- **backend**: emit per-request events as X-Events response header
- **downloads**: replace lengthy manifest sim with quick metadata pull
- **mobile-nav**: replace bottom tab strip with right-side hamburger drawer
- **maintenance**: add 'unwatch ended series' kind
- **maintenance**: reflow jobs table to stacked cards on mobile
- **maintenance**: show upstream-update availability above the Update LXC card
- **maintenance**: add 'Update LXC' kind that triggers /usr/local/bin/update
- **extension**: add Firefox MV3 extension to add the current tab to the library
- **maintenance**: add Komga series status push job
- **ui**: add favicon mirroring the header brand mark
- **logs**: pause auto-scroll when reading older entries
- **logs**: verbose logging + live journal tail in the UI
- **ui**: show rolling-rate ETA on running jobs
- rediscover series + chapter metadata in regen maintenance
- auto-detect series tags/genres from gallery-dl kwdict
- series publication status (Ongoing/Ended/Hiatus/Abandoned)
- add configurable chapter naming and maintenance rename jobs
- add watch checkbox when scheduling new series
- align lifecycle labels and add downloaded state

### Fix

- **komga**: emit Mylar-recognised status and harden REST push
- **frontend**: declutter active job card on mobile
- **docs**: green the strict mkdocs build
- **maintenance**: repair UI-triggered LXC update when path unit drifts inactive
- **backend**: parenthesise multi-type except clauses
- **frontend**: approve esbuild build script via pnpm-workspace.yaml
- **ui**: only render mobile drawer shadow when drawer is open
- **mobile-nav**: cover Firefox iOS pill safe area with a deeper extension
- **maintenance**: make the update-check actually work in production
- **mobile-nav**: cover Firefox iOS page bleed beneath bottom nav
- **frontend**: make mobile UI readable on phones
- **ci**: sync main, push annotated bump tag, publish GitHub release
- **deploy**: add service user to systemd-journal on update
- **maintenance**: mark in-flight jobs as failed on boot
- **poller**: mark target polled when a download is queued via submit/rebuild
- use strict null checks in lifecycle mapping

### Refactor

- **maintenance**: collapse MaintenanceJob+MaintenanceJobOut into one Pydantic model
- **targets**: collapse Target+TargetSummary+TargetOut into one Pydantic model
- **downloads**: collapse Download dataclass + DownloadOut Pydantic + translator
- **backend**: drop the db_lock plumbing now that the worker is serial
- **downloads**: serialise the worker and drop max_concurrent_downloads
- **extension**: add apiErrorMessage helper and drop ApiError duplication
- **tests**: centralise _write_cbz/_make_record helpers and drop gallery_holder
- **database**: add insert_returning_id helper and name claim retry limit
- **maintenance**: replace _execute if-chain with a kind→method dispatch dict
- **backend**: use BadRequestError/ConflictError/NotFoundError consistently
- **downloads**: extract DetailField and JobStepper from ActiveJobCard
- **downloads**: extract RecentRow into a sibling file
- **config**: extract FormSection and LibraryBackup from ConfigPanel
- **targets**: extract TargetRow + recencyKey into a sibling file
- **maintenance**: split MaintenancePanel sub-cards into siblings
- **frontend**: add useNotifyingMutation hook and consolidate notify+mutate sites
- **css**: drop !important + biome-ignore on .app-row-line overrides
- **maintenance**: write series.json before chapter rewrites in regen

### Perf

- **maintenance**: skip per-chapter requests during regen rediscovery
