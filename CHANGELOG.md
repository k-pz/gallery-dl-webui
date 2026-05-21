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
