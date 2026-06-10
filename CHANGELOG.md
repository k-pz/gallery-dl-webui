## v1.3.0 (2026-06-10)

### Feat

- **ui**: refresh-watched button in the library pane
- **targets**: bulk poll-watched endpoint
- **ui**: show plain results instead of live progress for finished jobs
- **ui**: result-focused job detail header for finished jobs

### Fix

- **ui**: stop mobile header clipping the wordmark descenders

## v1.2.1 (2026-06-09)

### Fix

- **deploy**: add uv --no-sync to serve:backend so read-only venv doesn't break startup

## v1.2.0 (2026-06-09)

### Feat

- **jobs**: viewport-aware layout — never two-column on phones
- **maintenance**: expandable result cell
- **maintenance**: add MaintResultCell expand/collapse component
- **running-jobs**: mirror URL subtitle for consistent density
- **css**: respect prefers-reduced-motion
- 44px pagination controls on phones
- 44px sort-direction toggle on phones
- **css**: 44px drawer close button on phones
- **css**: 44px touch targets for list/toolbar icon buttons on phones
- **theme**: add breakpoints map mirroring CSS --bp-* tokens
- **ui**: RecentRow shows failed chapter count
- **ui**: ProgressCard shows per-chapter outcomes + summary
- **ui**: status tones + labels for chapter outcomes
- **downloads**: progress endpoint returns persisted per-chapter truth
- **downloads**: worker persists discovered count + per-chapter outcomes
- **downloads**: persist per-chapter outcomes + discovered count
- **downloads**: capture per-chapter errors during gallery-dl run
- **downloads**: thread-scoped per-chapter error collector
- **downloads**: reconcile per-chapter outcomes
- **downloads**: add verbose-trace fields to schemas
- **db**: add verbose per-job trace columns

### Fix

- **ui**: address xhigh code-review findings in ux-copy-refinement
- **maintenance**: restore cancel-job tooltip for consistency with ActiveJobCard
- **maintenance-log**: label live status instead of raw backend token
- **job-stepper**: drop decorative icon row on phones
- **recent-row**: let chapter meta wrap on narrow rows
- **health-badge**: show 'checking' during load
- **recent-row**: spell the chapters unit
- **running-jobs**: spell the chapters unit
- **progress-card**: align transient labels to lifecycle + (untitled)
- **maintenance**: label status pill instead of raw backend token
- **css**: bottom safe-area guard on shell body at phone width
- **css**: bottom safe-area inset on footnote
- **css**: top safe-area inset on sticky header
- **maintenance-log**: scroll expanded log into view
- **library-backup**: cap import-error list in a scroll area
- **progress-card**: let chapter list scroll the page on phones
- **inline-confirm**: wrap message above buttons on phones
- **update-lxc**: full-width banner buttons on phones
- **update-lxc**: reflow preview-ref controls on phones
- **target-row**: reflow expanded controls on phones
- **recent-list**: reflow status + sort toolbar on phones
- **logs-panel**: stack filter controls one-per-row on phones
- **directory-picker**: wrap create-folder controls on phones
- **submit-form**: wrap URL+Download so the action reflows on phones
- **css**: hamburger touch target 40->44px
- **release**: finish release-workflow hardening (#54)
- **release**: merge rc sections into stable release notes (#53)

### Refactor

- **css**: centralize breakpoints behind postcss-custom-media tokens
- **downloads**: simplify outcome reconciliation + batch writes

## v1.1.0 (2026-05-26)

### Feat

- **maintenance**: show available tags + reflect tracked ref in footer (#49)
- **ui**: make logo link to library + a11y improvements (#48)
- **series**: make series status the primary pill, hide download status when idle (#47)

### Fix

- **release**: skip :latest tag on release-candidate Docker images (#52)
- **release**: chain tag-release off release.yml via workflow_run
- **release**: create annotated tags so `git push --follow-tags` pushes them

## v1.0.0 (2026-05-26)

### Feat

- **docker**: containerised app + GHCR publish workflow
- **release**: publish a GitHub Release on every `v*` tag push
- **release**: add `release:bump` mise task + workflow_dispatch release
- **maintenance**: version-aware update card + preview-ref tracking
- **release**: add mise run release:preview task
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
- **scripts**: propagate host SSH key into LXC for in-CT updates
- series publication status (Ongoing/Ended/Hiatus/Abandoned)
- **ui**: design system primitives + master-detail jobs layout
- **jobs**: running panel, queue-order sort, hide completed by default
- **realtime**: websocket event stream + parallel download / postprocess
- **deploy**: in-CT update command (/usr/local/bin/update)
- **ui**: amber/ink theme rework, list sort direction toggle
- **maintenance**: scope jobs to designated output dirs
- **docker**: production image + compose
- **maintenance**: rebuild_library job
- **config**: excluded directory names
- **maintenance**: cancellable jobs
- **postprocess**: emit Komga series.json + reading direction; series tags
- **maintenance**: live progress + log tail; rename in place; honor chapter_minor
- configurable chapter naming + maintenance jobs (#7)
- add configurable chapter naming and maintenance rename jobs
- add Watch checkbox on submit (default off) (#5)
- add watch checkbox when scheduling new series
- align lifecycle labels and add downloaded state
- **ui**: show chapter counter and per-chapter stages, not file counts
- **library**: yaml backup, series names, job stepper, list filters
- **targets**: group downloads by URL, watch + poll, dir-picker UI
- **frontend**: add dark mode (auto/light/dark, default auto)
- **downloads**: add cancel + requeue actions
- **postprocess**: per-download output dir with configurable root
- **scripts**: optionally mount a CIFS NAS share in proxmox-install
- **scripts**: add proxmox-uninstall.sh

### Fix

- **library**: stabilise Series row layout across watch states
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
- **postprocess**: re-parenthesise multi-exception except clauses
- **poller**: mark target polled when a download is queued via submit/rebuild
- **ui**: stack name onto its own line in narrow job rows
- **postprocess**: re-parenthesise multi-exception except clauses
- **postprocess**: parenthesise multi-exception except clauses
- use strict null checks in lifecycle mapping
- **worker**: skip already-packed chapters on watched-target re-polls
- **output_dirs**: drop silent 500-entry cap on direct children listing
- **library**: use validate_under_root(create=False) for import pre-flight
- **postprocess**: scan chapter dir to survive extension rewrites

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
- **ui**: unify "downloads"/"targets" copy as jobs/library
- align job/chapter state names across views (#3)
- **backend**: restructure into per-domain modules per fastapi best practices
- **scripts**: extract _proxmox-lib.sh for shared log/die/pct helpers
- **frontend**: extract ListHeader, ListToolbar, makeNeedleMatcher
- **frontend**: factor library backup fetch into lib/libraryBackup
- **frontend**: extract useOptimisticCancel for cancel-intent bookkeeping
- **frontend**: extract useDataInvalidators hook for query refresh
- **status**: convert JobStep to a discriminated union by kind
- **status**: move ACTIVE_STATUSES + add isActive helper
- **worker**: split _process into _extract_manifest / _execute_download / _handle_failure
- **worker**: replace _cancelled_ids set with a single _cancel_requested bool
- **gallery**: extract _inherit_shared_state for nested-job state plumbing
- **postprocess**: extract _safe_float for chapter number parsing
- **downloads**: factor _refresh_view helper for post-mutation reloads
- **storage**: add get_target_summary to drop list+scan in target routes
- **targets**: flatten update_target 4-arm dispatch via UNSET sentinel
- **library**: type _series_to_dict parameter
- **storage**: drop dead try/except around target_id row read
- **mise**: standardize task names on <verb>:<part>, parallelize aggregates
- **scripts**: drop standalone autologin script from proxmox-install

### Perf

- **maintenance**: skip per-chapter requests during regen rediscovery
