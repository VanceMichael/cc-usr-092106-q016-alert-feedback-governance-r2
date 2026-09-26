import unittest
from datetime import date, datetime

from src.labels import LabelBook, Reviewer
from src.leads import Conclusion, Lead, Trigger
from src.snapshots import ExclusionReason, build_snapshot

SIGNER = Reviewer("rev-1", frozenset({"label-signer"}), frozenset({"华东", "华北"}))
TRAIN_END = date(2026, 6, 30)
VALID_END = date(2026, 8, 31)
SALT = "test-salt"


def closed_lead(lead_id, closed_at, conclusion=Conclusion.FILED, **kwargs):
    lead = Lead(
        lead_id=lead_id,
        subject_ref=f"subj-{lead_id}",
        region="华东",
        trigger=Trigger("rule", "R-01", "v3", datetime(2026, 5, 1)),
        assigned_org="华东一局",
        **kwargs,
    )
    lead.close(conclusion, closed_at, evidence_refs=["EV-1"], effort_hours=2.0)
    return lead


def label_all(book, leads, at=datetime(2026, 9, 1)):
    for lead in leads:
        if lead.is_closed and lead.conclusion in (
            Conclusion.FILED,
            Conclusion.LEGAL_EXCEPTION,
        ):
            book.issue(
                lead, SIGNER,
                issued_at=at, evidence_refs=["EV-1"], basis="复核确认",
            )


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.book = LabelBook()

    def build(self, leads):
        return build_snapshot(
            leads, self.book,
            train_end=TRAIN_END, validation_end=VALID_END, salt=SALT,
        )

    def test_time_split_assigns_train_and_validation(self):
        leads = [
            closed_lead("L-1", datetime(2026, 6, 1)),
            closed_lead("L-2", datetime(2026, 7, 15)),
        ]
        label_all(self.book, leads)
        snapshot = self.build(leads)
        self.assertEqual([r.split for r in snapshot.usable("train")], ["train"])
        self.assertEqual(
            [r.split for r in snapshot.usable("validation")], ["validation"]
        )

    def test_unstable_records_are_excluded_with_reasons(self):
        open_lead = Lead(
            lead_id="L-open", subject_ref="s", region="华东",
            trigger=Trigger("rule", "R-01", "v3", datetime(2026, 5, 1)),
            assigned_org="华东一局",
        )
        duplicate = closed_lead("L-dup", datetime(2026, 6, 1),
                                duplicate_of="L-1")
        self_proving = closed_lead("L-self", datetime(2026, 6, 1))
        self_proving.self_proving = True
        data_error = closed_lead("L-err", datetime(2026, 6, 1),
                                 conclusion=Conclusion.DATA_ERROR)
        unlabeled = closed_lead("L-nolbl", datetime(2026, 6, 1),
                                conclusion=Conclusion.EVIDENCE_PENDING)
        late = closed_lead("L-late", datetime(2026, 9, 15))
        leads = [open_lead, duplicate, self_proving, data_error, unlabeled, late]
        label_all(self.book, leads)  # late 有标签但超出切分

        snapshot = self.build(leads)
        reasons = {e.lead_id: e.reason for e in snapshot.exclusions}
        self.assertEqual(reasons["L-open"], ExclusionReason.NOT_CLOSED)
        self.assertEqual(reasons["L-dup"], ExclusionReason.CROSS_REGION_DUPLICATE)
        self.assertEqual(reasons["L-self"], ExclusionReason.SELF_PROVING)
        self.assertEqual(reasons["L-err"], ExclusionReason.DATA_ERROR)
        self.assertEqual(reasons["L-nolbl"], ExclusionReason.NO_LABEL)
        self.assertEqual(reasons["L-late"], ExclusionReason.AFTER_CUTOFF)
        self.assertEqual(snapshot.usable(), [])

    def test_snapshot_records_are_desensitized(self):
        lead = closed_lead("L-1", datetime(2026, 6, 1))
        label_all(self.book, [lead])
        snapshot = self.build([lead])
        record = snapshot.usable()[0]
        self.assertNotIn("L-1", record.lead_ref)
        self.assertNotIn("subj-L-1", record.subject_hash)
        self.assertFalse(hasattr(record, "subject_ref"))

    def test_invalid_split_window_is_rejected(self):
        with self.assertRaises(ValueError):
            build_snapshot(
                [], self.book,
                train_end=VALID_END, validation_end=TRAIN_END, salt=SALT,
            )


if __name__ == "__main__":
    unittest.main()
