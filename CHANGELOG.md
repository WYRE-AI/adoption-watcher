# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
