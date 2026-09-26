import unittest

from src.leads import load_leads
from src.reviewers import load_reviewers
from src.labels import LabelLedger
from src.monitoring import load_deployments, load_metrics, compare_deployment
from src.audit import trace_leads

from tests.support import load_fixture


class AuditTrailTest(unittest.TestCase):
    def setUp(self):
        self.leads = load_leads(load_fixture("leads.json"))
        self.reviewers = load_reviewers(load_fixture("reviewers.json"))
        self.ledger = LabelLedger(load_fixture("labels.json"))

    def test_metric_drills_down_to_evidence_and_issuer(self):
        deployment = load_deployments(
            load_fixture("deployments.json"))[0]
        metrics = load_metrics(load_fixture("metrics.json"))
        report = compare_deployment(metrics, deployment)

        # 从 post 窗口的一条 positive 指标下钻
        post_positive = [
            h["lead_id"] for h in metrics["lead_hits"]
            if h["window"] == "post" and h["final_label"] == "positive"
        ]
        chain = trace_leads(post_positive, self.leads, self.ledger, self.reviewers)
        self.assertEqual(len(chain), 1)
        entry = chain[0]
        self.assertEqual(entry["lead_id"], "L-2026-1013")
        self.assertEqual(entry["trigger"]["version"], "ruleset-2026.07")
        version = entry["versions"][0]
        self.assertEqual(version["evidence_ids"], ["EV-1013-A"])
        self.assertTrue(version["evidence_sufficient"])
        self.assertEqual(version["issued_by"], "RV-002")
        self.assertEqual(version["issuer_display_name"], "李慎（虚构）")

    def test_appeal_history_is_fully_retained(self):
        chain = trace_leads(
            ["L-2026-1012"], self.leads, self.ledger, self.reviewers)
        versions = chain[0]["versions"]
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertEqual(versions[0]["status"], "superseded")
        self.assertEqual(versions[1]["status"], "issued")
        self.assertEqual(versions[1]["source"], "appeal")
        self.assertEqual(versions[1]["appeal_id"], "AP-2026-22")
        self.assertEqual(versions[1]["supersedes_version"], 1)

    def test_revoked_label_remains_visible_in_chain(self):
        chain = trace_leads(
            ["L-2026-1011"], self.leads, self.ledger, self.reviewers)
        versions = chain[0]["versions"]
        self.assertEqual(versions[0]["status"], "revoked")
        self.assertTrue(versions[0]["evidence_sufficient"])

    def test_unknown_lead_raises(self):
        with self.assertRaises(KeyError):
            trace_leads(["L-NOPE"], self.leads, self.ledger, self.reviewers)


if __name__ == "__main__":
    unittest.main()
