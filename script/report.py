"""Daily WYRE adoption digest — Gateway (legacy) + Conduit.

Hits each product's /api/admin/metrics endpoint, formats one combined
Slack Block Kit message, and posts to SLACK_WEBHOOK_URL.

Both endpoints return the same shape (conduit inherited the gateway's
metrics route): 30-day rolling counts — active orgs, top tools, plan
distribution, new-org signups. A product whose fetch fails is reported as
a warning block instead of killing the whole digest, and the run exits
non-zero afterwards so the Actions run shows red.

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

PRODUCTS = [
    {
        "key": "gateway",
        "label": "Gateway (legacy)",
        "base": os.environ.get("GATEWAY_BASE", "https://mcp.wyre.ai").rstrip("/"),
        "token": os.environ.get("GATEWAY_ADMIN_TOKEN", "").strip(),
        "token_env": "GATEWAY_ADMIN_TOKEN",
    },
    {
        "key": "conduit",
        "label": "Conduit",
        "base": os.environ.get("CONDUIT_BASE", "https://conduit.wyre.ai").rstrip("/"),
        "token": os.environ.get("CONDUIT_ADMIN_TOKEN", "").strip(),
        "token_env": "CONDUIT_ADMIN_TOKEN",
    },
]

SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
SNAPSHOT_PATH = Path("state/snapshot.json")


def fetch_metrics(product: dict) -> dict:
    if not product["token"]:
        raise RuntimeError(f"{product['token_env']} not set")
    req = urllib.request.Request(
        f"{product['base']}/api/admin/metrics",
        headers={
            "Authorization": f"Bearer {product['token']}",
            "Accept": "application/json",
            "User-Agent": "wyre-adoption-watcher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                f"{product['label']} rejected {product['token_env']} ({exc.code} {exc.reason}) — "
                f"rotate the repo secret to {product['base']}'s current ADMIN_API_KEY."
            ) from exc
        raise RuntimeError(
            f"{product['label']} returned {exc.code} {exc.reason} for "
            f"{product['base']}/api/admin/metrics"
        ) from exc


def fmt_int(n: int | str) -> str:
    return f"{int(n):,}"


def fmt_change(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def new_org_count(new_orgs: list) -> int:
    # Conduit buckets signups per day ({day, signups}); the legacy gateway
    # returned one item per org. Sum signups when bucketed, else count items.
    if new_orgs and isinstance(new_orgs[0], dict) and "signups" in new_orgs[0]:
        return sum(int(b.get("signups", 0)) for b in new_orgs)
    return len(new_orgs)


def product_blocks(product: dict, curr: dict, prev: dict | None) -> list[dict]:
    active_orgs = curr.get("active_orgs", {}).get("orgs", []) or []
    active_count = curr.get("active_orgs", {}).get("count", len(active_orgs))
    total_calls = sum(int(o.get("tool_calls", 0)) for o in active_orgs)

    prev_active = (prev or {}).get("active_orgs", {}).get("orgs", []) or []
    prev_calls = sum(int(o.get("tool_calls", 0)) for o in prev_active)
    prev_count = (prev or {}).get("active_orgs", {}).get("count", len(prev_active))

    calls_delta = total_calls - prev_calls if prev else 0
    orgs_delta = active_count - prev_count if prev else 0

    plan_dist = curr.get("plan_distribution", []) or []
    plan_summary = ", ".join(
        f"{p.get('plan', '?')}: {fmt_int(p.get('count', 0))}" for p in plan_dist
    ) or "_no data_"

    blocks: list[dict] = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{product['label']}*"},
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
                    "text": f"*New orgs (last 7d)*\n{fmt_int(new_org_count(curr.get('new_orgs', []) or []))}",
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

    top_tools = curr.get("top_tools", []) or []
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

    return blocks


def load_previous() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        prev = json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    # Pre-rename snapshots were the gateway payload at the top level.
    if "schema" not in prev and "active_orgs" in prev:
        return {"gateway": prev}
    return prev


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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prev_all = load_previous()
    snapshot: dict = {"schema": 2}
    warnings: list[str] = []

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: Adoption · {today}"},
        }
    ]

    for product in PRODUCTS:
        print(f"Fetching {product['label']} metrics from {product['base']}/api/admin/metrics …")
        try:
            curr = fetch_metrics(product)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            warnings.append(f":warning: {product['label']}: {exc}")
            # Keep yesterday's data so the next successful run diffs sanely.
            if product["key"] in prev_all:
                snapshot[product["key"]] = prev_all[product["key"]]
            continue
        print(
            "  active_orgs:",
            curr.get("active_orgs", {}).get("count"),
            "· top_tools:",
            len(curr.get("top_tools", []) or []),
        )
        blocks.extend(product_blocks(product, curr, prev_all.get(product["key"])))
        snapshot[product["key"]] = curr

    if warnings:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(warnings)},
            }
        )

    dashboards = " · ".join(
        f"<{p['base']}/admin/dashboard|{p['label']} dashboard>" for p in PRODUCTS
    )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"{dashboards} · adoption-watcher"}],
        }
    )

    post_slack({"blocks": blocks})

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"Snapshot written to {SNAPSHOT_PATH}")
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
