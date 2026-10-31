# wyre-adoption-watcher

Daily Slack digest of WYRE product adoption for **Conduit** (conduit.wyre.ai).
Pulls `/api/admin/metrics`:

- Active orgs (30-day rolling)
- Total tool calls and per-org breakdown
- Top vendors by tool calls
- Current pricing and subscription view
- New orgs (14d)

Runs every day at 14:05 UTC (five minutes after `stars-watcher` so the two
digests don't land on top of each other). The two watchers are deliberately
complementary: `stars-watcher` tracks external *reach* (stars, registry
coverage, PulseMCP traffic); this one tracks internal *usage*.

> Renamed from `gateway-adoption-watcher` on 2026-08-20 when Conduit
> coverage was added; GitHub redirects the old URL. The legacy MCP gateway
> (`mcp.wyre.ai`) has since been retired. This job does not fetch it, and
> there is no `GATEWAY_BASE` / `GATEWAY_ADMIN_TOKEN` setting.

## Setup

1. Delivery uses the shared **WYRE Notifier** Slack app (WYRE AI workspace,
   manifest in `wyre-technology/.github` → `slack-app/notifier/`) via the
   org-level `SLACK_NOTIFIER_BOT_TOKEN` Actions secret — nothing to set per
   repo. The target channel is `SLACK_CHANNEL_ID` in
   `.github/workflows/daily.yml` (currently `C0BSHBQQBQ8`,
   #product-notifications).
2. Add the Conduit admin token (pipe straight from Azure — never paste values):
   ```
   # Conduit — conduit-prod Container App secret
   az containerapp secret show -n conduit-prod-gateway -g rg-conduit-prod \
     --secret-name admin-api-key --query value -o tsv \
     | gh secret set CONDUIT_ADMIN_TOKEN --repo wyre-technology/adoption-watcher
   ```
3. (Optional) Override the Conduit base URL — defaults to `https://conduit.wyre.ai`:
   ```
   gh variable set CONDUIT_BASE --body "…" --repo wyre-technology/adoption-watcher
   ```
4. Trigger manually to verify formatting:
   ```
   gh workflow run daily.yml --repo wyre-technology/adoption-watcher
   ```

## How it works

`script/report.py` is plain stdlib Python. It hits Conduit's metrics
endpoint with its bearer token, formats a Slack Block Kit message, and
posts it via the WYRE Notifier bot. It saves the response to
`state/snapshot.json` (`schema: 2`, keyed by product) and diffs against the
previous run for "since last run" deltas.

If the fetch fails, the section is replaced by a warning block and the run
exits non-zero so the Actions run shows red.

Use dry-run mode to print the Block Kit JSON and plain-text digest without
posting or writing state. Set `DRY_RUN=1` or pass `--dry-run`. Add
`--fixture PATH` to render from a saved metrics JSON (fixture runs are always
dry runs), for example
`python3 script/report.py --fixture tests/fixtures/metrics-sample.json`. Set
`INTERNAL_ORG_IDS` to a comma-separated list to override the default WYRE
internal organization.

Test orgs are excluded too. `TEST_ORG_IDS` and `TEST_ORG_DOMAINS` in
`script/report.py` list orgs that are only used for testing (currently
"Sachshaus Testing" and owners on `sachshaus.net`). They apply even when
`INTERNAL_ORG_IDS` is overridden. Conduit already drops orgs it flags as demo
or synthetic, so only add test orgs that Conduit does not flag.

## Window

The metrics endpoint returns 30-day rolling counts. When it grows a
`?window=24h` query parameter, swap that in for a true day-over-day delta —
same digest shape.
