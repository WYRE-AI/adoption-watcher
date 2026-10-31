"""Daily Conduit adoption digest with dry-run, internal and test org exclusion, and Conduit pricing."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Source of truth: WYRE-AI/conduit src/billing/prices.ts.
# PER_SEAT_PRICE_CENTS is the flat $39 per billable seat for direct and MSP
# customers. RESELLER_PER_SEAT_CENTS is the $18 per-seat wholesale rate before
# the reseller markup. ORG_FEE_CENTS is now zero.
PER_SEAT_PRICE_CENTS = 3_900
RESELLER_PER_SEAT_CENTS = 1_800
ORG_FEE_CENTS = 0

PRICING_NOTE = (
    f"${PER_SEAT_PRICE_CENTS / 100:.0f}/seat direct & MSP · "
    f"${RESELLER_PER_SEAT_CENTS / 100:.0f}/seat wholesale + reseller markup · "
    f"no org fee"
)

DEFAULT_INTERNAL_ORG_ID = "L-Fk69VfrntBjgVxOvWJX"
INTERNAL_ORG_DOMAINS = ("wyre.ai", "wyretechnology.com")

# Test orgs that are not customers. Conduit's own metrics already drop orgs
# flagged demo or synthetic; these are test orgs it does not flag. They are
# always excluded, even when INTERNAL_ORG_IDS is overridden. Add new ones here
# by org id, with the org name as a comment-style value.
TEST_ORG_IDS = {
    "JmBzai1r48eXOJg7nPSi-": "Sachshaus Testing",
}
# Owner email domains used only for test signups.
TEST_ORG_DOMAINS = ("sachshaus.net",)

PRODUCTS = [
    {
        "key": "conduit",
        "label": "Conduit",
        "base": os.environ.get("CONDUIT_BASE", "https://conduit.wyre.ai").rstrip("/"),
        "token": os.environ.get("CONDUIT_ADMIN_TOKEN", "").strip(),
        "token_env": "CONDUIT_ADMIN_TOKEN",
    },
]

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "").strip()
SNAPSHOT_PATH = Path("state/snapshot.json")


def get_internal_org_ids() -> set[str]:
    configured = os.environ.get("INTERNAL_ORG_IDS", DEFAULT_INTERNAL_ORG_ID)
    return {org_id.strip() for org_id in configured.split(",") if org_id.strip()}


def is_internal_org(org: dict, internal_org_ids: set[str]) -> bool:
    org_id = org.get("org_id") or org.get("id") or ""
    if org_id in internal_org_ids or org_id in TEST_ORG_IDS:
        return True
    tags = org.get("metric_tags") or org.get("tags") or []
    if isinstance(tags, list) and "exclude-from-metrics" in tags:
        return True
    if org.get("exclude_from_metrics") is True or org.get("exclude_from_metrics") == "exclude-from-metrics":
        return True
    owner_email = org.get("owner_email") or ""
    if "@" not in owner_email:
        return False
    domain = owner_email.rsplit("@", 1)[1].strip().lower()
    return domain in INTERNAL_ORG_DOMAINS or domain in TEST_ORG_DOMAINS


def customer_orgs(metrics: dict, internal_org_ids: set[str] | None = None) -> list[dict]:
    if internal_org_ids is None:
        internal_org_ids = get_internal_org_ids()
    orgs = metrics.get("active_orgs", {}).get("orgs") or []
    if not isinstance(orgs, list):
        return []
    return [org for org in orgs if not is_internal_org(org, internal_org_ids)]


def adjusted_active_count(metrics: dict, internal_org_ids: set[str] | None = None) -> int:
    active = metrics.get("active_orgs") or {}
    orgs = active.get("orgs") or []
    if internal_org_ids is None:
        internal_org_ids = get_internal_org_ids()
    customer_count = len(
        [org for org in orgs if isinstance(org, dict) and not is_internal_org(org, internal_org_ids)]
    )
    if active.get("count") is None:
        return customer_count
    internal_count = sum(
        1 for org in orgs if isinstance(org, dict) and is_internal_org(org, internal_org_ids)
    )
    return max(0, int(active.get("count") or 0) - internal_count)


def fetch_metrics(product: dict) -> dict:
    if not product["token"]:
        raise RuntimeError(f"{product['token_env']} not set")
    request = urllib.request.Request(
        f"{product['base']}/api/admin/metrics",
        headers={
            "Authorization": f"Bearer {product['token']}",
            "Accept": "application/json",
            "User-Agent": "wyre-adoption-watcher",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                f"{product['label']} rejected {product['token_env']} ({exc.code} {exc.reason}). "
                f"Rotate the repo secret to {product['base']}'s current ADMIN_API_KEY."
            ) from exc
        raise RuntimeError(
            f"{product['label']} returned {exc.code} {exc.reason} for "
            f"{product['base']}/api/admin/metrics"
        ) from exc


def fmt_int(value: int | str) -> str:
    return f"{int(value):,}"


def fmt_change(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def new_org_count(new_orgs: list, internal_org_ids: set[str] | None = None) -> int:
    orgs = new_orgs or []
    if orgs and isinstance(orgs[0], dict) and "signups" in orgs[0]:
        if internal_org_ids is None:
            internal_org_ids = get_internal_org_ids()
        return sum(
            int(item.get("signups") or 0)
            for item in orgs
            if not (isinstance(item, dict) and is_internal_org(item, internal_org_ids))
        )
    if internal_org_ids is None:
        internal_org_ids = get_internal_org_ids()
    return sum(
        1
        for org in orgs
        if isinstance(org, dict) and not is_internal_org(org, internal_org_ids)
    )


def product_blocks(
    product: dict,
    curr: dict,
    prev: dict | None = None,
    internal_org_ids: set[str] | None = None,
) -> list[dict]:
    orgs = customer_orgs(curr, internal_org_ids)
    active_count = adjusted_active_count(curr, internal_org_ids)
    total_calls = sum(int(org.get("tool_calls") or 0) for org in orgs)

    previous_orgs = (prev or {}).get("active_orgs", {}).get("orgs") or []
    previous_customer_orgs = [
        org
        for org in previous_orgs
        if not is_internal_org(org, internal_org_ids or get_internal_org_ids())
    ]
    previous_calls = sum(int(org.get("tool_calls") or 0) for org in previous_customer_orgs)
    previous_active_count = adjusted_active_count(prev or {}, internal_org_ids or get_internal_org_ids())

    if prev:
        calls_delta = total_calls - previous_calls
        orgs_delta = active_count - previous_active_count
    else:
        calls_delta = 0
        orgs_delta = 0

    growth = curr.get("growth") or {}
    paying_count = int(growth.get("payingOrgs") or 0)
    reseller_count = int(growth.get("resellerOrgs") or 0)
    trial_distribution = next(
        (entry for entry in curr.get("plan_distribution") or [] if entry.get("plan") == "trial"),
        None,
    )
    if trial_distribution is not None:
        trial_count = int(trial_distribution.get("count") or 0)
    else:
        trial_count = sum(1 for org in orgs if org.get("plan") == "trial")

    blocks = [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{product['label']}*"}},
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Tool calls (30d rolling)*\n{fmt_int(total_calls)}"
                        f"{f' ({fmt_change(calls_delta)} vs last run)' if prev else ''}"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Active orgs (30d)*\n{fmt_int(active_count)}"
                        f"{f' ({fmt_change(orgs_delta)})' if prev else ''}"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*New orgs (14d)*\n"
                        f"{fmt_int(new_org_count(curr.get('new_orgs_recent') or curr.get('new_orgs') or [], internal_org_ids))}"
                    ),
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Paying orgs*\n{fmt_int(paying_count)}"},
                {"type": "mrkdwn", "text": f"*Reseller orgs*\n{fmt_int(reseller_count)}"},
                {"type": "mrkdwn", "text": f"*Trials*\n{fmt_int(trial_count)}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Paying and reseller counts are Conduit's dashboard figures",
                }
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Current pricing*\n{PRICING_NOTE}"}},
    ]

    if orgs:
        lines = "\n".join(
            f"• {org.get('org_name', '?')}: {fmt_int(org.get('tool_calls') or 0)}"
            for org in orgs[:8]
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top orgs by tool calls*\n{lines}"},
            }
        )

    top_tools = curr.get("top_tools") or []
    if top_tools:
        per_vendor: dict[str, int] = {}
        for tool in top_tools:
            slug = tool.get("vendor_slug") or "?"
            per_vendor[slug] = per_vendor.get(slug, 0) + int(tool.get("call_count") or 0)
        ranked = sorted(per_vendor.items(), key=lambda item: -item[1])[:8]
        lines = "\n".join(f"• {slug}: {fmt_int(call_count)}" for slug, call_count in ranked)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top vendors by tool calls*\n{lines}"},
            }
        )

    return blocks


def normalize_snapshot(previous: object) -> dict:
    """Return the normalized Conduit snapshot."""
    if not isinstance(previous, dict):
        return {}
    if not isinstance(previous.get("conduit"), dict):
        return {}
    return {"conduit": previous["conduit"]}


def load_previous() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        previous = json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return normalize_snapshot(previous)


def post_slack(payload: dict) -> None:
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        print("SLACK_BOT_TOKEN/SLACK_CHANNEL_ID not set - printing payload instead:", file=sys.stderr)
        print(json.dumps(payload, indent=2))
        return
    body = {
        "channel": SLACK_CHANNEL_ID,
        "text": "Daily adoption digest",
        "username": "Adoption Watcher",
        "icon_emoji": ":chart_with_upwards_trend:",
        **payload,
    }
    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
        if not result.get("ok"):
            sys.exit(f"chat.postMessage failed: {result.get('error')}")


def block_text(block: dict) -> str:
    if block.get("type") == "header":
        return block.get("text", {}).get("text", "")
    if block.get("type") == "context":
        return " ".join(
            element.get("text") or ""
            for element in block.get("elements") or []
        )
    if block.get("type") == "section":
        lines: list[str] = []
        if block.get("text", {}).get("text"):
            lines.extend(block["text"]["text"].split("\n"))
        for field in block.get("fields") or []:
            if field.get("text"):
                lines.extend(field["text"].split("\n"))
        return "\n".join(lines)
    return ""


def blocks_to_text(blocks: list[dict]) -> str:
    rendered = []
    for block in blocks:
        text = block_text(block).strip()
        lines = []
        for line in text.split("\n"):
            line = line.strip().replace("*", "").replace("`", "")
            if line.startswith("• "):
                line = f"- {line[2:]}"
            lines.append(line)
        if text:
            rendered.append("\n".join(lines))
    return "\n\n".join(rendered)


def build_digest(
    metrics: dict | None,
    previous: dict | None = None,
    warnings: list[str] | None = None,
) -> tuple[list[dict], str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: Adoption · {today}"},
        },
    ]
    if warnings:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(warnings)},
            }
        )
    elif metrics is not None:
        for product in PRODUCTS:
            blocks.extend(product_blocks(product, metrics, (previous or {}).get(product["key"])))

    context_text = (
        f"<{PRODUCTS[0]['base']}/admin/dashboard|Conduit dashboard> · adoption-watcher · "
        "Excludes WYRE internal and test orgs"
    )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context_text}],
        }
    )
    return blocks, json.dumps({"blocks": blocks}, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="WYRE adoption digest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture", help="Read metrics JSON from a file instead of fetching")
    args = parser.parse_args()
    # A fixture is mock data: never post it or save it as the snapshot.
    dry_run = args.dry_run or bool(args.fixture) or os.environ.get("DRY_RUN") == "1"

    previous = load_previous()
    warnings: list[str] = []
    snapshot: dict = {"schema": 2}
    metrics: dict | None = None

    try:
        if args.fixture:
            metrics = json.loads(Path(args.fixture).read_text())
        else:
            print(f"Fetching {PRODUCTS[0]['label']} metrics from {PRODUCTS[0]['base']}/api/admin/metrics …")
            metrics = fetch_metrics(PRODUCTS[0])
    except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        print(f"  FAILED: {exc}", file=sys.stderr)
        warnings.append(f":warning: {PRODUCTS[0]['label']}: {exc}")

    blocks, payload_json = build_digest(metrics, previous, warnings)
    if dry_run:
        print(payload_json)
        print("\nPlain text digest:")
        print(blocks_to_text(blocks))
        return 1 if warnings else 0

    post_slack({"blocks": blocks})
    if metrics is None:
        if "conduit" in previous:
            snapshot["conduit"] = previous["conduit"]
    else:
        snapshot["conduit"] = metrics
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"Snapshot written to {SNAPSHOT_PATH}")
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
