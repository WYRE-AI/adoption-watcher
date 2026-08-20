# wyre-adoption-watcher

Daily Slack digest of WYRE product adoption — **Conduit** (conduit.wyre.ai)
and the **legacy Gateway** (mcp.wyre.ai) side by side. Pulls each product's
`/api/admin/metrics` endpoint:

- Active orgs (30-day rolling)
- Total tool calls and per-org breakdown
- Top vendors by tool calls
- Plan distribution
- New org signups

Runs every day at 14:05 UTC (five minutes after `stars-watcher` so the two
digests don't land on top of each other). The two watchers are deliberately
complementary: `stars-watcher` tracks external *reach* (stars, registry
coverage, PulseMCP traffic); this one tracks internal *usage*.

> Renamed from `gateway-adoption-watcher` on 2026-08-20 when Conduit
> coverage was added; GitHub redirects the old URL.

## Setup

1. Delivery uses the shared **WYRE Notifier** Slack app (WYRE AI workspace,
   manifest in `wyre-technology/.github` → `slack-app/notifier/`) via the
   org-level `SLACK_NOTIFIER_BOT_TOKEN` Actions secret — nothing to set per
   repo. The target channel is `SLACK_CHANNEL_ID` in
   `.github/workflows/daily.yml` (currently `C0BSHBQQBQ8`,
   #product-notifications).
2. Add the admin tokens (pipe straight from Azure — never paste values):
   ```
   # Legacy gateway — mcpgw-prod-kv Key Vault
   az keyvault secret show --vault-name mcpgw-prod-kv --name admin-api-key --query value -o tsv \
     | gh secret set GATEWAY_ADMIN_TOKEN --repo wyre-technology/adoption-watcher

   # Conduit — conduit-prod Container App secret
   az containerapp secret show -n conduit-prod-gateway -g rg-conduit-prod \
     --secret-name admin-api-key --query value -o tsv \
     | gh secret set CONDUIT_ADMIN_TOKEN --repo wyre-technology/adoption-watcher
   ```
3. (Optional) Override the base URLs — default to `https://mcp.wyre.ai` and
   `https://conduit.wyre.ai`:
   ```
   gh variable set GATEWAY_BASE --body "…" --repo wyre-technology/adoption-watcher
   gh variable set CONDUIT_BASE --body "…" --repo wyre-technology/adoption-watcher
   ```
4. Trigger manually to verify formatting:
   ```
   gh workflow run daily.yml --repo wyre-technology/adoption-watcher
   ```

## How it works

`script/report.py` is plain stdlib Python. It hits each product's metrics
endpoint with its bearer token, formats one combined Slack Block Kit message
(one section per product), and posts it via the WYRE Notifier bot. It saves the responses
to `state/snapshot.json` (keyed per product, `schema: 2`; pre-rename flat
snapshots are read as gateway-only) and diffs against the previous run for
"since last run" deltas.

If one product's fetch fails, its section is replaced by a warning block, the
other product still posts, and the run exits non-zero so the Actions run
shows red.

## Window

Both metrics endpoints return 30-day rolling counts. When they grow a
`?window=24h` query parameter, swap that in for a true day-over-day delta —
same digest shape.
