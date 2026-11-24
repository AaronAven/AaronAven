# Incidents

| date (UTC) | what happened | impact | fix |
|---|---|---|---|
| 2026-11-11 | Cloud container shut down about 10 min after the $500 paper runs started | No fill-rate data collected | Run bots on Aaron's Mac with `run_all.sh`; cloud runs are for testing only |
| 2026-11-11 | Paper bot's hours-to-resolution filter compared hours with seconds, so it found no candidates | No trades in first smoke test | Fixed (`max_hours * 3600`) before any results were recorded |
| 2026-11-11 | Alpaca bot parsed nanosecond timestamps 5 hours off | Would have mistimed sessions | Fixed and tested before use (Alpaca bot is now shelved) |
| 2026-11-19 | Aaron's Mac not reachable from the cloud session (no Remote Control folder shared) | Bots can't be started on the Mac remotely | Aaron runs `run_all.sh` himself, or shares a folder via the desktop app |
