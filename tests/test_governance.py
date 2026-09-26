import unittest
from datetime import date, datetime

from src.governance import build_batch_report
from src.labels import LabelBook, LabelValue, Reviewer
from src.leads import Conclusion, Lead, Trigger
from src.metrics import collect_metrics

SIGNER = Reviewer("rev-1", frozenset({"label-signer"}), frozenset({"华东"}))


def make_lead(lead_id, version, conclusion=Conclusion.FILED, hours=2.0,
              closed=True):
    lead = Lead(
        lead_id=lead_id,
        subject_ref=f"subj-{lead_id}",
        region="华东",
        trigger=Trigger("rule", "R-01", version, datetime(2026, 5, 1)),
        assigned_org="华东一局",
    )
    if closed:
        lead.close(conclusion, datetime(2026, 6, 1),
                   evidence_refs=["EV-1"], effort_hours=hours)
    return lead


class MetricsTest(unittest.TestCase):
    def test_distribution_and_burden_per_version(self):
        book = LabelBook()
        leads = [
            make_lead("L-1", "v3", Conclusion.FILED, hours=4.0),
            make_lead("L-2", "v3", Conclusion.LEGAL_EXCEPTION, hours=2.0),
            make_lead("L-3", "v4", Conclusion.FILED, hours=1.0),
            make_lead("L-4", "v4", closed=False),
        ]
        for lead in leads[:3]:
            book.issue(lead, SIGNER, issued_at=datetime(2026, 6, 2),
                       evidence_refs=["EV-1"], basis="复核确认")

        metrics = collect_metrics(leads, book)
        v3 = metrics["rule:R-01@v3"]
        self.assertEqual(v3.total_hits, 2)
        self.assertEqual(v3.by_conclusion[Conclusion.FILED], 1)
        self.assertEqual(v3.by_label[LabelValue.POSITIVE], 1)
        self.assertEqual(v3.by_label[LabelValue.NEGATIVE], 1)
        self.assertEqual(v3.effort_hours, 6.0)
        self.assertEqual(v3.hours_per_hit, 3.0)
        self.assertEqual(v3.positive_rate, 0.5)

        v4 = metrics["rule:R-01@v4"]
        self.assertEqual(v4.open_leads, 1)
        self.assertEqual(len(v4.contributors), 2)


class GovernanceTest(unittest.TestCase):
    def setUp(self):
        self.book = LabelBook()
        self.leads = [
            make_lead("L-1", "v3", Conclusion.FILED, hours=4.0),
            make_lead("L-2", "v3", Conclusion.LEGAL_EXCEPTION, hours=2.0),
            make_lead("L-3", "v4", Conclusion.FILED, hours=1.0),
            make_lead("L-4", "v4", closed=False),  # 尚未结案，应被排除
        ]
        for lead in self.leads[:3]:
            self.book.issue(lead, SIGNER, issued_at=datetime(2026, 6, 2),
                            evidence_refs=["EV-1"], basis="复核确认")
        self.report = build_batch_report(
            self.leads, self.book,
            train_end=date(2026, 6, 30), validation_end=date(2026, 8, 31),
            salt="s",
        )

    def test_explain_covers_usable_and_excluded(self):
        text = self.report.explain()
        self.assertIn("训练集 3 条", text)
        self.assertIn("排除 1 条", text)
        self.assertIn("not_closed", text)

    def test_audit_trail_returns_issuance_basis(self):
        trail = self.report.audit_trail("rule:R-01@v3")
        self.assertEqual(len(trail), 2)
        for version in trail:
            self.assertEqual(version.basis, "复核确认")
            self.assertEqual(version.issued_by, "rev-1")
            self.assertTrue(version.evidence_refs)

    def test_version_diff_shows_what_new_rule_changed(self):
        diff = self.report.version_diff("rule:R-01@v3", "rule:R-01@v4")
        self.assertEqual(diff.delta_hits, 0)
        self.assertEqual(diff.delta_positive_rate, 0.5)
        self.assertEqual(diff.delta_hours_per_hit, -2.5)
        self.assertEqual(diff.delta_open_leads, 1)


if __name__ == "__main__":
    unittest.main()
