# UI Stale Live Cycle Warning

## Summary

The private UI previously showed only `systemctl` service state for the live
bot. That meant the dashboard could display `active/running` even when no new
decision rows had been written for many hours.

## What Changed

- Dashboard payload now computes live-row freshness from the latest recorded
  cycle timestamp.
- Dashboard marks an active service as `stale` when the latest decision row is
  older than the expected cadence window.
- Dashboard now shows:
  - latest cycle age
  - a stale warning when no fresh cycle has been recorded
- History page now shows a stale warning banner when the latest recorded cycle
  is old.

## Why

`active/running` only proves the service process still exists. It does not prove
that the bot is still completing cycles and writing fresh artifacts.

## Verification

- `python -m unittest tests.test_ui_services tests.test_ui_app`

