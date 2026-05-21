# Design decisions worth knowing

The load-bearing choices in the codebase, and the reasoning behind them.

- **One worker, one DB connection.** Simplifies everything: no row-level
  locking, no fairness concerns, no concurrent-job tax on the disk. The
  cost is a serialised queue, which has been fine in practice.
- **Sim-then-real.** Running gallery-dl in simulation mode first lets us
  precompute the file manifest (and capture the series name) before we
  decide whether to start writing. The simulation pass is what makes the
  progress UI possible without instrumenting gallery-dl's internals.
- **Manifest stored in SQLite, live progress in memory.** Restart-safe
  history of *what was expected* (so you can re-render a completed job's
  per-chapter breakdown) without paying disk for *real-time* progress, which
  is only meaningful while the worker is alive.
- **Stem-level progress matching.** Filenames-without-extension are the
  invariant that survives gallery-dl's mid-flight extension rewrites.
- **Watched targets via `skip_chapter`.** Re-running an already-fetched
  series doesn't waste bandwidth, but the manifest still says "0 new
  chapters" which the UI shows truthfully.
- **Path validation at every entry.** Every user-supplied path (output dir
  on submit, default output dir in config, output dir on PATCH target,
  paths in YAML import) goes through `validate_under_root` so a misconfig
  surfaces as a 400, never as a half-completed write somewhere outside the
  sandbox.
- **`ProtectSystem=strict` + write-probe.** Saving the config does a real
  `write_bytes(b"")` + `unlink` on the configured paths, so a missing
  `ReadWritePaths=` whitelist throws immediately instead of failing the
  first download.
- **Cancellation via `StopExtraction`.** Hijacking gallery-dl's own
  documented "stop nicely" exception means the dispatcher unwinds cleanly
  and `run_download` still returns an `exit_code`, so accounting stays
  consistent.
- **Boot recovery flips `extracting`/`running` to `failed`.** The
  alternative is "row stuck forever, requires manual SQL" — the lossier
  but consistent path is better.
- **Single source of truth for paths is the database.** Settings only knows
  about the data dir; the postprocess root and default output dir live in
  `app_config` so the UI can change them at runtime without a service
  restart.
- **Auto-detected metadata never overwrites a user override.** Series
  publication status is read from the sim-pass kwdict and persisted only
  when the target's `series_status` is still blank; the manual PATCH wins
  forever after. The alternative — letting every re-poll re-clobber the
  field with the extractor's latest guess — would silently undo the user's
  correction. Same shape generalises to any future auto-then-override field.
