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

1. Create a Slack incoming webhook in the channel you want this digest in.
2. Add it as a repo secret:
   ```
   gh secret set SLACK_WEBHOOK_URL --repo wyre-technology/adoption-watcher
   ```
3. Add the admin tokens (pipe straight from Azure — never paste values):
   ```
   # Legacy gateway — mcpgw-prod-kv Key Vault
   az keyvault secret show --vault-name mcpgw-prod-kv --name admin-api-key --query value -o tsv \
     | gh secret set GATEWAY_ADMIN_TOKEN --repo wyre-technology/adoption-watcher

   # Conduit — conduit-prod Container App secret
   az containerapp secret show -n conduit-prod-gateway -g rg-conduit-prod \
     --secret-name admin-api-key --query value -o tsv \
     | gh secret set CONDUIT_ADMIN_TOKEN --repo wyre-technology/adoption-watcher
   ```
4. (Optional) Override the base URLs — default to `https://mcp.wyre.ai` and
   `https://conduit.wyre.ai`:
   ```
   gh variable set GATEWAY_BASE --body "…" --repo wyre-technology/adoption-watcher
   gh variable set CONDUIT_BASE --body "…" --repo wyre-technology/adoption-watcher
   ```
5. Trigger manually to verify formatting:
   ```
   gh workflow run daily.yml --repo wyre-technology/adoption-watcher
   ```

## How it works

`script/report.py` is plain stdlib Python. It hits each product's metrics
endpoint with its bearer token, formats one combined Slack Block Kit message
(one section per product), and posts to the webhook. It saves the responses
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
