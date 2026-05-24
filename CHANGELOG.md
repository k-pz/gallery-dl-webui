## v1.8.1 (2026-05-24)

### Refactor

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

## v1.8.0 (2026-05-24)

### Feat

- **downloads**: replace lengthy manifest sim with quick metadata pull

## v1.7.0 (2026-05-22)

### Feat

- **mobile-nav**: replace bottom tab strip with right-side hamburger drawer

## v1.6.0 (2026-05-22)

### Feat

- **maintenance**: add 'unwatch ended series' kind

## v1.5.1 (2026-05-22)

### Fix

- **mobile-nav**: cover Firefox iOS pill safe area with a deeper extension

## v1.5.0 (2026-05-22)

### Feat

- **maintenance**: reflow jobs table to stacked cards on mobile

### Refactor

- **css**: drop !important + biome-ignore on .app-row-line overrides

## v1.4.2 (2026-05-22)

### Fix

- **maintenance**: make the update-check actually work in production

## v1.4.1 (2026-05-22)

### Fix

- **mobile-nav**: cover Firefox iOS page bleed beneath bottom nav

## v1.4.0 (2026-05-22)

### Feat

- **maintenance**: show upstream-update availability above the Update LXC card
- **maintenance**: add 'Update LXC' kind that triggers /usr/local/bin/update

## v1.3.0 (2026-05-21)

### Feat

- **extension**: add Firefox MV3 extension to add the current tab to the library

## v1.2.0 (2026-05-21)

### Feat

- **maintenance**: add Komga series status push job

## v1.1.3 (2026-05-21)

### Fix

- **frontend**: make mobile UI readable on phones

## v1.1.2 (2026-05-21)

### Refactor

- **maintenance**: write series.json before chapter rewrites in regen

## v1.1.1 (2026-05-21)

### Perf

- **maintenance**: skip per-chapter requests during regen rediscovery

## v1.1.0 (2026-05-21)

### Feat

- **ui**: add favicon mirroring the header brand mark
- **logs**: pause auto-scroll when reading older entries

### Fix

- **ci**: sync main, push annotated bump tag, publish GitHub release

## v1.0.1 (2026-05-21)

### Fix

- **deploy**: add service user to systemd-journal on update

## v1.0.0 (2026-05-21)

### Feat

- **logs**: verbose logging + live journal tail in the UI
- **ui**: show rolling-rate ETA on running jobs
- rediscover series + chapter metadata in regen maintenance
- auto-detect series tags/genres from gallery-dl kwdict
- series publication status (Ongoing/Ended/Hiatus/Abandoned)
- add configurable chapter naming and maintenance rename jobs
- add watch checkbox when scheduling new series
- align lifecycle labels and add downloaded state

### Fix

- **maintenance**: mark in-flight jobs as failed on boot
- **poller**: mark target polled when a download is queued via submit/rebuild
- use strict null checks in lifecycle mapping
