import json
import sys
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
        blocks = report.product_blocks(report.PRODUCTS[0], self.metrics)
        rendered = json.dumps(blocks)
        self.assertIn("no org fee", rendered)
        self.assertIn("$39/seat", rendered)
        self.assertNotIn("Plan mix", rendered)
        self.assertNotIn("free", rendered)
        self.assertNotIn("pro", rendered)
        self.assertNotIn("business", rendered)

        internal = report.get_internal_org_ids()
        self.assertIn("L-Fk69VfrntBjgVxOvWJX", internal)
        customer_metrics = {
            "active_orgs": self.metrics["active_orgs"],
            "growth": self.metrics["growth"],
            "new_orgs": self.metrics["new_orgs"],
        }
        blocks = report.product_blocks(
            report.PRODUCTS[0], customer_metrics, internal_org_ids=internal
        )
        text = json.dumps(blocks)
        self.assertNotIn("WYRE Technology", text)
        self.assertIn("Acme Synthetic", text)

    def test_internal_org_is_excluded_from_totals_and_top_list(self):
        orgs = [
            {"org_id": "L-Fk69VfrntBjgVxOvWJX", "org_name": "WYRE Technology", "tool_calls": 999},
            {"org_id": "ORG-SYNTH-1", "org_name": "Acme Synthetic", "tool_calls": 20},
        ]
        metrics = {"active_orgs": {"count": 2, "orgs": orgs}}
        blocks = report.product_blocks(report.PRODUCTS[0], metrics)
        text = json.dumps(blocks)
        self.assertIn("1", text)
        self.assertNotIn("999", text)
        self.assertNotIn("WYRE Technology", text)

    def test_missing_growth_key_does_not_crash(self):
        blocks = report.product_blocks(report.PRODUCTS[0], {"active_orgs": {"count": 0, "orgs": []}})
        self.assertTrue(blocks)


class DryRunTests(unittest.TestCase):
    @mock.patch.object(report, "post_slack")
    @mock.patch.object(report, "load_previous")
    @mock.patch.object(report, "SNAPSHOT_PATH")
    @mock.patch.object(report, "fetch_metrics")
    def test_dry_run_does_not_post_or_write_snapshot(
        self, fetch_metrics, snapshot_path, load_previous, post_slack
    ):
        fetch_metrics.return_value = {}
        snapshot_path.exists.return_value = True
        load_previous.return_value = {}
        with mock.patch.object(sys, "argv", ["report.py", "--dry-run", "--fixture", str(FIXTURE)]):
            exit_code = report.main()

        self.assertEqual(exit_code, 0)
        post_slack.assert_not_called()
        snapshot_path.write_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
