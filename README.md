# wyre-adoption-watcher

Daily Slack digest of WYRE product adoption for **Conduit** (conduit.wyre.ai).
It pulls `/api/admin/metrics` and posts a Block Kit digest to the WYRE Notifier
Slack app.

## Current pricing

The digest reports the current Conduit pricing: a flat $39 per billable seat for
direct and MSP customers, or $18 per seat wholesale plus the reseller markup.
There is no organization fee.

## Setup

1. Delivery uses the shared **WYRE Notifier** Slack app via the org-level
   `SLACK_NOTIFIER_BOT_TOKEN` Actions secret. The target channel is
   `SLACK_CHANNEL_ID` in `.github/workflows/daily.yml`.
2. Add the Conduit admin token:
   ```bash
   az containerapp secret show -n conduit-prod -g rg-conduit-prod \
     --secret-name admin-api-key --query value -o tsv \
     | gh secret set CONDUIT_ADMIN_TOKEN --repo wyre-technology/adoption-watcher
   ```
3. Optionally override the Conduit base URL:
   ```bash
   gh variable set CONDUIT_BASE --body "…" --repo wyre-technology/adoption-watcher
   ```
4. Trigger manually to verify formatting:
   ```bash
   gh workflow run daily.yml --repo wyre-technology/adoption-watcher
   ```

## Behavior

The job is Conduit-only. It reads `/api/admin/metrics`, renders the digest,
posts it to Slack, and saves a snapshot for daily deltas. Use dry-run mode to
print the Block Kit JSON and plain-text digest without posting or writing state.

Run it locally with:

```bash
python script/report.py --dry-run --fixture tests/fixtures/metrics-sample.json
```

Set `DRY_RUN=1` or pass `--dry-run` to enable dry-run mode. Set
`INTERNAL_ORG_IDS` to a comma-separated list to override the default WYRE
internal organization.

## Window

The metrics endpoint returns 30-day rolling counts. When it grows a
`?window=24h` query parameter, swap that in for a true day-over-day delta.
