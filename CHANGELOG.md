# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Current pricing instead of legacy plan mix.** The digest no longer prints the raw `organizations.plan` counts (`business`, `free`, `pro`, `conduit`, `trial`), which reflected retired tiers. It now shows paying orgs, reseller orgs and trials, plus the current pricing from Conduit's `src/billing/prices.ts`: $39/seat for direct and MSP customers, $18/seat wholesale plus reseller markup, and no org fee (the $399 base fee is gone).
- **Active orgs use the true total.** `active_orgs.count` is used instead of the length of the 50-row org list, minus WYRE internal orgs, and the previous snapshot gets the same adjustment so the delta compares like with like.
- **New orgs window labelled correctly.** The endpoint reports the last 14 days, so the field now reads "New orgs (14d)" instead of "last 7d".

### Added

- **WYRE internal org exclusion.** The WYRE Technology tenant (default `INTERNAL_ORG_IDS=L-Fk69VfrntBjgVxOvWJX`), orgs owned by `wyre.ai` or `wyretechnology.com` addresses, and orgs tagged `exclude-from-metrics` are left out of active orgs, tool calls, top orgs and new orgs.
- **Test org exclusion.** Test orgs that Conduit does not flag as demo or synthetic are excluded the same way as internal orgs, by org id (`TEST_ORG_IDS`, currently "Sachshaus Testing") or owner domain (`TEST_ORG_DOMAINS`, currently `sachshaus.net`). The digest footer now reads "Excludes WYRE internal and test orgs".
- **Dry run.** `--dry-run` (or `DRY_RUN=1`) prints the Block Kit JSON and a plain-text rendering without posting to Slack or writing `state/snapshot.json`. `--fixture PATH` reads metrics from a JSON file and always implies dry run.
- **Unit tests** in `tests/` (stdlib `unittest`, synthetic fixtures), run in CI alongside `ruff check script/ tests/`.

### Removed

- Leftover gateway branches in snapshot loading. Only the `conduit` key of an old snapshot is read.
- **Legacy Gateway metrics.** The daily digest is Conduit-only (`conduit.wyre.ai`). It no longer fetches the retired MCP gateway at `mcp.wyre.ai`, and `GATEWAY_BASE` / `GATEWAY_ADMIN_TOKEN` are gone from the workflow and setup. Older `state/snapshot.json` files that still have a `gateway` key, or a pre-schema flat gateway payload, load cleanly — that data is ignored and not written back.

### Added

- **PR-triggered CI workflow** (`.github/workflows/ci.yml`): every pull request now runs a Python 3.12 syntax check and import smoke test of `script/report.py`, `ruff` lint (pinned 0.16.5), and JSON validation of `state/snapshot.json`. Closes the repo's automated-checks gap (Vanta `github-code-change-automated-checks-enabled`).

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
