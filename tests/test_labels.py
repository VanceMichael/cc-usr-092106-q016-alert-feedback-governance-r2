import unittest
from datetime import datetime

from src.labels import (
    CONCLUSION_TO_LABEL,
    EvidenceInsufficientError,
    LabelAuthorizationError,
    LabelBook,
    LabelSource,
    LabelValue,
    Reviewer,
    UnresolvableConclusionError,
)
from src.leads import Conclusion, Lead, Trigger


def make_lead(lead_id="L-1", region="华东", conclusion=Conclusion.FILED):
    lead = Lead(
        lead_id=lead_id,
        subject_ref=f"subj-{lead_id}",
        region=region,
        trigger=Trigger("rule", "R-01", "v3", datetime(2026, 5, 1)),
        assigned_org="华东一局",
    )
    if conclusion is not None:
        lead.close(
            conclusion,
            datetime(2026, 6, 1),
            evidence_refs=["EV-1"],
            effort_hours=3.0,
        )
    return lead


SIGNER = Reviewer("rev-1", frozenset({"label-signer"}), frozenset({"华东"}))
NOW = datetime(2026, 6, 2)


class LabelIssueTest(unittest.TestCase):
    def test_filed_conclusion_yields_positive_label(self):
        book = LabelBook()
        version = book.issue(
            make_lead(), SIGNER,
            issued_at=NOW, evidence_refs=["EV-1"], basis="现场核查确认违规",
        )
        self.assertEqual(version.value, LabelValue.POSITIVE)
        self.assertEqual(version.version, 1)
        self.assertEqual(version.source, LabelSource.REVIEW)

    def test_legal_exception_yields_negative_label(self):
        book = LabelBook()
        version = book.issue(
            make_lead(conclusion=Conclusion.LEGAL_EXCEPTION), SIGNER,
            issued_at=NOW, evidence_refs=["EV-1"], basis="属政策豁免范围",
        )
        self.assertEqual(version.value, LabelValue.NEGATIVE)

    def test_unclosed_lead_cannot_be_labeled(self):
        book = LabelBook()
        with self.assertRaises(EvidenceInsufficientError):
            book.issue(
                make_lead(conclusion=None), SIGNER,
                issued_at=NOW, evidence_refs=["EV-1"], basis="x",
            )

    def test_pending_evidence_is_not_a_negative_sample(self):
        book = LabelBook()
        for conclusion in (
            Conclusion.EVIDENCE_PENDING,
            Conclusion.INCOMPLETE,
            Conclusion.DATA_ERROR,
        ):
            self.assertNotIn(conclusion, CONCLUSION_TO_LABEL)
            with self.assertRaises(UnresolvableConclusionError):
                book.issue(
                    make_lead(conclusion=conclusion), SIGNER,
                    issued_at=NOW, evidence_refs=["EV-1"], basis="x",
                )

    def test_reviewer_must_hold_signer_role(self):
        book = LabelBook()
        outsider = Reviewer("rev-2", frozenset({"viewer"}), frozenset({"华东"}))
        with self.assertRaises(LabelAuthorizationError):
            book.issue(
                make_lead(), outsider,
                issued_at=NOW, evidence_refs=["EV-1"], basis="x",
            )

    def test_reviewer_must_be_authorized_for_region(self):
        book = LabelBook()
        outsider = Reviewer("rev-3", frozenset({"label-signer"}), frozenset({"华北"}))
        with self.assertRaises(LabelAuthorizationError):
            book.issue(
                make_lead(), outsider,
                issued_at=NOW, evidence_refs=["EV-1"], basis="x",
            )

    def test_evidence_and_basis_are_required(self):
        book = LabelBook()
        with self.assertRaises(EvidenceInsufficientError):
            book.issue(make_lead(), SIGNER, issued_at=NOW, evidence_refs=[], basis="x")
        with self.assertRaises(EvidenceInsufficientError):
            book.issue(
                make_lead(), SIGNER,
                issued_at=NOW, evidence_refs=["EV-1"], basis="",
            )


class LabelVersionTest(unittest.TestCase):
    def setUp(self):
        self.book = LabelBook()
        self.lead = make_lead()
        self.book.issue(
            self.lead, SIGNER,
            issued_at=NOW, evidence_refs=["EV-1"], basis="初审确认",
        )

    def test_appeal_creates_new_version_and_keeps_history(self):
        appealed = self.book.appeal(
            self.lead, SIGNER,
            value=LabelValue.NEGATIVE,
            issued_at=datetime(2026, 7, 1),
            evidence_refs=["EV-9"],
            basis="申诉复核推翻原结论",
        )
        self.assertEqual(appealed.version, 2)
        self.assertEqual(appealed.source, LabelSource.APPEAL)
        history = self.book.history(self.lead.lead_id)
        self.assertEqual([v.value for v in history],
                         [LabelValue.POSITIVE, LabelValue.NEGATIVE])
        self.assertEqual(self.book.current(self.lead.lead_id).value,
                         LabelValue.NEGATIVE)

    def test_case_outcome_creates_new_version(self):
        version = self.book.record_case_outcome(
            self.lead,
            case_ref="CASE-100",
            value=LabelValue.POSITIVE,
            recorded_at=datetime(2026, 8, 1),
            basis="案件审结确认违法事实",
        )
        self.assertEqual(version.version, 2)
        self.assertEqual(version.source, LabelSource.CASE_OUTCOME)
        self.assertEqual(version.issued_by, "case:CASE-100")

    def test_appeal_requires_existing_label(self):
        with self.assertRaises(ValueError):
            self.book.appeal(
                make_lead(lead_id="L-2"), SIGNER,
                value=LabelValue.NEGATIVE,
                issued_at=NOW, evidence_refs=["EV-1"], basis="x",
            )

    def test_duplicate_issue_is_rejected(self):
        with self.assertRaises(ValueError):
            self.book.issue(
                self.lead, SIGNER,
                issued_at=NOW, evidence_refs=["EV-2"], basis="重复签发",
            )


if __name__ == "__main__":
    unittest.main()
