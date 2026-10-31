import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "script"))
import report

FIXTURE = Path(__file__).parent / "fixtures" / "metrics-sample.json"
OLD_SNAPSHOT = Path(__file__).parent / "fixtures" / "old-snapshot.json"


class ReportTests(unittest.TestCase):
    def test_conduit_only_product(self):
        self.assertEqual([product["key"] for product in report.PRODUCTS], ["conduit"])
        self.assertEqual(report.PRODUCTS[0]["base"], "https://conduit.wyre.ai")

    def test_old_snapshot_with_gateway_key_loads(self):
        with OLD_SNAPSHOT.open() as snapshot_file:
            snapshot = json.load(snapshot_file)
        normalized = report.normalize_snapshot(snapshot)
        self.assertNotIn("gateway", normalized)
        self.assertEqual(normalized, {"conduit": snapshot["conduit"]})


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.metrics = json.loads(FIXTURE.read_text())

    def test_digest_uses_current_pricing_and_excludes_internal_org(self):
        blocks, _ = report.build_digest(self.metrics)
        rendered = json.dumps(blocks)
        self.assertIn("no org fee", rendered)
        self.assertIn("$39/seat", rendered)
        self.assertNotIn("Plan mix", rendered)
        self.assertIsNone(re.search(r"\b(?:free|pro|business)\b", report.blocks_to_text(blocks), re.IGNORECASE))

    def test_active_org_count_uses_true_total_minus_internal(self):
        internal_org_id = report.DEFAULT_INTERNAL_ORG_ID
        metrics = {
            "active_orgs": {
                "count": 3,
                "orgs": [
                    {"org_id": internal_org_id, "org_name": "WYRE Technology", "plan": "conduit", "tool_calls": 99},
                    {"org_id": "ORG-CUSTOMER-1", "org_name": "Acme Synthetic", "plan": "conduit", "tool_calls": 2},
                    {"org_id": "ORG-CUSTOMER-2", "org_name": "Northwind Synthetic", "plan": "trial", "tool_calls": 1},
                ],
            }
        }
        blocks = report.product_blocks(report.PRODUCTS[0], metrics, internal_org_ids={internal_org_id})
        fields = blocks[2]["fields"]
        self.assertIn("2", fields[1]["text"])
        self.assertNotIn("99", fields[1]["text"])

    def test_previous_active_count_is_adjusted_for_like_for_like_delta(self):
        internal_org_id = report.DEFAULT_INTERNAL_ORG_ID
        current = {
            "active_orgs": {
                "count": 3,
                "orgs": [
                    {"org_id": internal_org_id, "org_name": "WYRE Technology", "plan": "conduit", "tool_calls": 10},
                    {"org_id": "ORG-CUSTOMER-1", "org_name": "Acme Synthetic", "plan": "conduit", "tool_calls": 4},
                    {"org_id": "ORG-CUSTOMER-2", "org_name": "Northwind Synthetic", "plan": "trial", "tool_calls": 6},
                ],
            }
        }
        previous = {
            "active_orgs": {
                "count": 2,
                "orgs": [{"org_id": "ORG-CUSTOMER-1", "org_name": "Acme Synthetic", "plan": "conduit", "tool_calls": 5}],
            }
        }
        blocks = report.product_blocks(report.PRODUCTS[0], current, previous, {internal_org_id})
        fields = blocks[2]["fields"]
        self.assertIn("2", fields[1]["text"])
        self.assertIn("(0)", fields[1]["text"])

    def test_trials_come_from_plan_distribution(self):
        metrics = {
            "active_orgs": {"count": 1, "orgs": [{"org_id": "ORG-CUSTOMER-1", "org_name": "Acme Synthetic", "plan": "conduit", "tool_calls": 1}]},
            "plan_distribution": [{"plan": "trial", "count": 2}],
        }
        blocks = report.product_blocks(report.PRODUCTS[0], metrics)
        fields = blocks[3]["fields"]
        self.assertIn("2", fields[2]["text"])

    def test_new_orgs_use_recent_14d_window(self):
        blocks = report.product_blocks(report.PRODUCTS[0], self.metrics)
        fields = blocks[2]["fields"]
        new_orgs_text = fields[2]["text"]
        self.assertIn("New orgs (14d)", new_orgs_text)
        self.assertNotIn("New orgs (last 7d)", new_orgs_text)
        self.assertIn("1", new_orgs_text)

    def test_digest_includes_contexts_and_dashboard_link(self):
        blocks, _ = report.build_digest(self.metrics)
        contexts = [block for block in blocks if block.get("type") == "context"]
        self.assertEqual(len(contexts), 2)
        self.assertIn("Paying and reseller counts are Conduit's dashboard figures", contexts[0]["elements"][0]["text"])
        self.assertIn(
            "<https://conduit.wyre.ai/admin/dashboard|Conduit dashboard>",
            contexts[1]["elements"][0]["text"],
        )
        self.assertIn("Excludes WYRE internal and test orgs", contexts[1]["elements"][0]["text"])


    def test_test_orgs_are_excluded_by_id_and_owner_domain(self):
        metrics = {
            "active_orgs": {
                "count": 3,
                "orgs": [
                    {"org_id": "JmBzai1r48eXOJg7nPSi-", "org_name": "Sachshaus Testing", "plan": "conduit", "tool_calls": 500},
                    {"org_id": "ORG-SYNTH-1", "org_name": "Acme Synthetic", "plan": "conduit", "tool_calls": 20},
                    {"org_id": "ORG-SYNTH-2", "org_name": "Northwind Synthetic", "plan": "conduit", "tool_calls": 5},
                ],
            },
            "new_orgs_recent": [
                {"org_id": "ORG-SYNTH-9", "org_name": "Domain Test Org", "owner_email": "someone+test@sachshaus.net"},
                {"org_id": "JmBzai1r48eXOJg7nPSi-", "org_name": "Sachshaus Testing"},
                {"org_id": "ORG-SYNTH-3", "org_name": "Contoso Synthetic", "owner_email": "owner@contoso.example"},
            ],
        }
        # Test orgs stay excluded even when INTERNAL_ORG_IDS is overridden.
        blocks = report.product_blocks(report.PRODUCTS[0], metrics, internal_org_ids={"SOMETHING-ELSE"})
        text = report.blocks_to_text(blocks)
        self.assertNotIn("Sachshaus Testing", text)
        self.assertNotIn("500", text)
        self.assertIn("Tool calls (30d rolling)\n25", text)
        self.assertIn("Active orgs (30d)\n2", text)
        self.assertIn("New orgs (14d)\n1", text)


class MainTests(unittest.TestCase):
    def test_normal_mode_fetches_once_and_posts_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "snapshot.json"
            with (
                mock.patch.object(report, "SNAPSHOT_PATH", snapshot_path),
                mock.patch.object(report, "load_previous") as load_previous,
                mock.patch.object(report, "post_slack") as post_slack,
                mock.patch.object(report, "fetch_metrics") as fetch_metrics,
            ):
                fetch_metrics.return_value = json.loads(FIXTURE.read_text())
                load_previous.return_value = {}
                with mock.patch.object(sys, "argv", ["report.py"]):
                    exit_code = report.main()

            self.assertEqual(exit_code, 0)
            fetch_metrics.assert_called_once()
            post_slack.assert_called_once()
            self.assertTrue(snapshot_path.exists())


    def test_normal_mode_diffs_against_previous_conduit_snapshot(self):
        current = json.loads(FIXTURE.read_text())
        previous_conduit = json.loads(FIXTURE.read_text())
        previous_conduit["active_orgs"]["count"] -= 1
        previous_conduit["active_orgs"]["orgs"] = [
            {**org, "tool_calls": int(org.get("tool_calls") or 0) - 2}
            for org in previous_conduit["active_orgs"]["orgs"]
        ]
        customer_orgs = report.customer_orgs(current)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(report, "SNAPSHOT_PATH", Path(temp_dir) / "snapshot.json"),
            mock.patch.object(report, "load_previous", return_value={"conduit": previous_conduit}),
            mock.patch.object(report, "post_slack") as post_slack,
            mock.patch.object(report, "fetch_metrics", return_value=current),
            mock.patch.object(sys, "argv", ["report.py"]),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(report.main(), 0)
        text = report.blocks_to_text(post_slack.call_args.args[0]["blocks"])
        self.assertIn(f"(+{2 * len(customer_orgs)} vs last run)", text)
        self.assertIn("(+1)", text)

    def test_fixture_without_dry_run_flag_never_posts(self):
        with (
            mock.patch.object(report, "SNAPSHOT_PATH") as snapshot_path,
            mock.patch.object(report, "load_previous", return_value={}),
            mock.patch.object(report, "post_slack") as post_slack,
            mock.patch.object(sys, "argv", ["report.py", "--fixture", str(FIXTURE)]),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(report.main(), 0)
        post_slack.assert_not_called()
        snapshot_path.write_text.assert_not_called()

    @mock.patch.object(report, "post_slack")
    @mock.patch.object(report, "load_previous")
    @mock.patch.object(report, "SNAPSHOT_PATH")
    @mock.patch.object(report, "fetch_metrics")
    def test_fetch_failure_returns_warning_and_nonzero(
        self, fetch_metrics, snapshot_path, load_previous, post_slack
    ):
        fetch_metrics.side_effect = RuntimeError(
            "Conduit rejected CONDUIT_ADMIN_TOKEN (401 Unauthorized). "
            "Rotate the repo secret to https://conduit.wyre.ai's current ADMIN_API_KEY."
        )
        load_previous.return_value = {}
        with mock.patch.object(sys, "argv", ["report.py"]):
            exit_code = report.main()

        self.assertEqual(exit_code, 1)
        fetch_metrics.assert_called_once()
        post_slack.assert_called_once()
        blocks = post_slack.call_args.args[0]["blocks"]
        warning = next(
            block
            for block in blocks
            if block.get("type") == "section" and ":warning: Conduit:" in block["text"]["text"]
        )
        self.assertIn("Rotate the repo secret", warning["text"]["text"])


class DryRunTests(unittest.TestCase):
    @mock.patch.object(report, "post_slack")
    @mock.patch.object(report, "load_previous")
    @mock.patch.object(report, "SNAPSHOT_PATH")
    @mock.patch.object(report, "fetch_metrics")
    def test_dry_run_does_not_fetch_post_or_write_snapshot(
        self, fetch_metrics, snapshot_path, load_previous, post_slack
    ):
        fetch_metrics.return_value = {}
        snapshot_path.exists.return_value = True
        load_previous.return_value = {}
        with mock.patch.object(sys, "argv", ["report.py", "--dry-run", "--fixture", str(FIXTURE)]):
            exit_code = report.main()

        self.assertEqual(exit_code, 0)
        fetch_metrics.assert_not_called()
        post_slack.assert_not_called()
        snapshot_path.write_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
