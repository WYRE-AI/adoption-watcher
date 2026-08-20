# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Delivery moved to #product-notifications in the WYRE AI workspace.** Posts now go through the shared "WYRE Notifier" Slack app (`chat.postMessage`, org-level `SLACK_NOTIFIER_BOT_TOKEN` secret, channel pinned in the workflow) instead of the old wyretalk incoming webhook; `SLACK_WEBHOOK_URL` is retired.

### Added

- **Conduit adoption coverage — repo renamed `gateway-adoption-watcher` → `adoption-watcher`.** The daily digest now pulls `/api/admin/metrics` from both Conduit (`conduit.wyre.ai`, new `CONDUIT_ADMIN_TOKEN` secret / `CONDUIT_BASE` var) and the legacy Gateway, rendering one combined message with a section per product. Snapshot moves to a per-product `schema: 2` shape (old flat snapshots are read as gateway-only, so first-run deltas survive the migration). Conduit's day-bucketed `new_orgs` (`{day, signups}`) is summed rather than counted. A single product failing becomes a warning block instead of killing the digest; the run still exits non-zero so Actions flags it.

### Fixed

- Daily digest had been failing every run with `HTTP 401: Unauthorized` from
  `/api/admin/metrics` because the `GATEWAY_ADMIN_TOKEN` repo secret did not
  match the gateway's production `ADMIN_API_KEY`. Secret rotated to the live
  value; the scheduled run now authenticates.

### Changed

- `fetch_metrics()` now exits with a clear, actionable message on a 401/403
  from the gateway ("token does not match the gateway's ADMIN_API_KEY …")
  instead of dumping a raw `urllib` traceback.
- Bumped `actions/checkout` (v4 → v5) and `actions/setup-python` (v5 → v6),
  both pinned to commit SHAs, to move off the deprecated Node 20 runtime
  ahead of the June 16, 2026 forced cutover.
