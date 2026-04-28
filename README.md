# wyre-gateway-adoption-watcher

Daily Slack digest of WYRE MCP Gateway adoption. Pulls metrics from the
gateway's `/api/admin/metrics` endpoint:

- Active orgs (30-day rolling)
- Total tool calls and per-org breakdown
- Top vendors by tool calls
- Plan distribution
- New org signups

Runs every day at 14:05 UTC (five minutes after `stars-watcher` so the two
digests don't land on top of each other).

## Setup

1. Create a Slack incoming webhook in the channel you want this digest in
   (different channel from stars-watcher is fine — they're separate digests).
2. Add it as a repo secret:
   ```
   gh secret set SLACK_WEBHOOK_URL --repo wyre-technology/gateway-adoption-watcher
   ```
3. Add the gateway admin token (from `mcpgw-prod-kv` Key Vault → `admin-api-key`):
   ```
   az keyvault secret show --vault-name mcpgw-prod-kv --name admin-api-key --query value -o tsv \
     | gh secret set GATEWAY_ADMIN_TOKEN --repo wyre-technology/gateway-adoption-watcher
   ```
4. (Optional) Override the gateway base URL — defaults to `https://mcp.wyre.ai`:
   ```
   gh variable set GATEWAY_BASE --body "https://mcp.wyre.ai" --repo wyre-technology/gateway-adoption-watcher
   ```
5. Trigger manually to verify formatting:
   ```
   gh workflow run daily.yml --repo wyre-technology/gateway-adoption-watcher
   ```

## How it works

`script/report.py` is plain stdlib Python. Hits the gateway with the bearer
token, parses the JSON metrics payload, formats it as Slack Block Kit, posts
to the webhook. Saves the response to `state/snapshot.json` and diffs against
yesterday's snapshot to compute "since last run" deltas.

## Window

The gateway's metrics endpoint currently returns 30-day rolling counts. When
the endpoint grows a `?window=24h` query parameter, swap that in for a true
day-over-day delta — same digest shape.
