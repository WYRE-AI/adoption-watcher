"""Daily WYRE MCP Gateway adoption digest.

Hits the gateway's /api/admin/metrics endpoint, formats the result as a
Slack Block Kit message, and posts to SLACK_WEBHOOK_URL.

The metrics endpoint currently returns 30-day rolling counts (active orgs,
top tools, credit burn, new orgs, plan distribution). The endpoint can be
extended to take a `?window=24h` query later — when that lands, drop in a
windowed version next to this one for a true day-over-day delta.

Stdlib only — no pip install needed in CI.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GATEWAY_BASE = os.environ.get("GATEWAY_BASE", "https://mcp.wyre.ai").rstrip("/")
ADMIN_TOKEN = os.environ.get("GATEWAY_ADMIN_TOKEN", "").strip()
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
SNAPSHOT_PATH = Path("state/snapshot.json")


def fetch_metrics() -> dict:
    if not ADMIN_TOKEN:
        sys.exit("GATEWAY_ADMIN_TOKEN not set")
    req = urllib.request.Request(
        f"{GATEWAY_BASE}/api/admin/metrics",
        headers={
            "Authorization": f"Bearer {ADMIN_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "wyre-gateway-adoption-watcher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sys.exit(
                f"Gateway rejected GATEWAY_ADMIN_TOKEN ({exc.code} {exc.reason}). "
                f"The token does not match the gateway's ADMIN_API_KEY for "
                f"{GATEWAY_BASE} — rotate the repo secret to the current prod value."
            )
        sys.exit(f"Gateway returned {exc.code} {exc.reason} for {GATEWAY_BASE}/api/admin/metrics")


def fmt_int(n: int | str) -> str:
    return f"{int(n):,}"


def fmt_change(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def format_message(curr: dict, prev: dict | None) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    active_orgs = curr.get("active_orgs", {}).get("orgs", []) or []
    active_count = curr.get("active_orgs", {}).get("count", len(active_orgs))
    total_calls = sum(int(o.get("tool_calls", 0)) for o in active_orgs)

    prev_active = (prev or {}).get("active_orgs", {}).get("orgs", []) or []
    prev_calls = sum(int(o.get("tool_calls", 0)) for o in prev_active)
    prev_count = (prev or {}).get("active_orgs", {}).get("count", len(prev_active))

    calls_delta = total_calls - prev_calls if prev else 0
    orgs_delta = active_count - prev_count if prev else 0

    top_tools = curr.get("top_tools", []) or []

    plan_dist = curr.get("plan_distribution", []) or []
    plan_summary = ", ".join(
        f"{p.get('plan', '?')}: {fmt_int(p.get('count', 0))}" for p in plan_dist
    ) or "_no data_"

    new_orgs = curr.get("new_orgs", []) or []

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: Gateway adoption · {today}"},
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Tool calls (30d rolling)*\n{fmt_int(total_calls)} ({fmt_change(calls_delta)} vs last run)",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Active orgs (30d)*\n{fmt_int(active_count)} ({fmt_change(orgs_delta)})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Plan mix*\n{plan_summary}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*New orgs (last 7d)*\n{fmt_int(len(new_orgs))}",
                },
            ],
        },
    ]

    if active_orgs:
        top = active_orgs[:8]
        lines = "\n".join(
            f"• `{o.get('org_name', '?')}` ({o.get('plan', '?')}) — {fmt_int(o.get('tool_calls', 0))}"
            for o in top
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top orgs by tool calls*\n{lines}"},
            }
        )

    if top_tools:
        # Collapse vendor-level totals so the digest is readable.
        per_vendor: dict[str, int] = {}
        for t in top_tools:
            slug = t.get("vendor_slug", "?")
            per_vendor[slug] = per_vendor.get(slug, 0) + int(t.get("call_count", 0))
        ranked = sorted(per_vendor.items(), key=lambda kv: -kv[1])[:8]
        lines = "\n".join(f"• `{slug}` — {fmt_int(n)}" for slug, n in ranked)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top vendors by tool calls*\n{lines}"},
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"<{GATEWAY_BASE}/admin/dashboard|Open admin dashboard> · gateway-adoption-watcher",
                }
            ],
        }
    )

    return {"blocks": blocks}


def post_slack(payload: dict) -> None:
    if not SLACK_WEBHOOK:
        print("SLACK_WEBHOOK_URL not set — printing payload instead:", file=sys.stderr)
        print(json.dumps(payload, indent=2))
        return
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode().strip()
        if body and body != "ok":
            print(f"Slack response: {body}", file=sys.stderr)


def main() -> int:
    print(f"Fetching gateway metrics from {GATEWAY_BASE}/api/admin/metrics …")
    curr = fetch_metrics()
    print(
        "  active_orgs:",
        curr.get("active_orgs", {}).get("count"),
        "· top_tools:",
        len(curr.get("top_tools", []) or []),
    )

    prev: dict | None = None
    if SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(SNAPSHOT_PATH.read_text())
        except json.JSONDecodeError:
            prev = None

    payload = format_message(curr, prev)
    post_slack(payload)

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(curr, indent=2, sort_keys=True) + "\n")
    print(f"Snapshot written to {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
