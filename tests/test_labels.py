import unittest

from src.leads import load_leads
from src.reviewers import load_reviewers, PermissionError_
from src.labels import LabelLedger, LabelError, OUTCOME_LABELS
from src.validation import SchemaError

from tests.support import load_fixture


def make_lead(lead_id="L-TEST-1", region="110101", subject="S-T1",
              outcome="legal_exception", stage="closed"):
    """基于契约最小字段构造一条虚构线索。"""
    return {
        "lead_id": lead_id,
        "subject_ref": subject,
        "region_code": region,
        "cross_region_group": None,
        "trigger": {
            "kind": "rule",
            "version": "ruleset-2026.04",
            "rule_ids": ["R-FLOW-11"],
            "model_score": None,
        },
        "input_watermark": {
            "as_of": "2026-03-01T02:00:00+08:00",
            "source_snapshots": [
                {"source": "filings", "snapshot_id": "fil-test"},
            ],
        },
        "dispatch": {
            "scope": "regional",
            "regions": [region],
            "dispatched_at": "2026-03-01T09:00:00+08:00",
        },
        "stage": stage,
        "conclusion": None if stage in ("new", "assigned", "checking") else {
            "outcome": outcome,
            "reason_codes": ["test-reason"],
            "narrative": "测试虚构线索",
            "decided_at": "2026-03-20T10:00:00+08:00",
        },
        "created_at": "2026-03-01T08:00:00+08:00",
        "updated_at": "2026-03-20T10:00:00+08:00",
    }


class IssuanceGuardTest(unittest.TestCase):
    def setUp(self):
        self.reviewers = load_reviewers(load_fixture("reviewers.json"))

    def test_investigator_cannot_issue(self):
        ledger = LabelLedger()
        with self.assertRaises(PermissionError_):
            ledger.issue(
                make_lead(), self.reviewers,
                issued_by="RV-003", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-T1"], evidence_sufficient=True,
            )

    def test_inactive_reviewer_rejected(self):
        ledger = LabelLedger()
        with self.assertRaises(PermissionError_):
            ledger.issue(
                make_lead(), self.reviewers,
                issued_by="RV-006", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-T1"], evidence_sufficient=True,
            )

    def test_region_scope_enforced(self):
        ledger = LabelLedger()
        # RV-004 只有浙江 330106 辖区，不得签北京线索
        with self.assertRaises(PermissionError_):
            ledger.issue(
                make_lead(region="110101"), self.reviewers,
                issued_by="RV-004", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-T1"], evidence_sufficient=True,
            )
        # 辖区内可签发
        rec = ledger.issue(
            make_lead(region="330106"), self.reviewers,
            issued_by="RV-004", issued_at="2026-03-21T09:00:00+08:00",
            source="field_check", evidence_ids=["EV-T1"], evidence_sufficient=True,
        )
        self.assertEqual(rec["status"], "issued")

    def test_open_lead_cannot_be_labeled(self):
        ledger = LabelLedger()
        with self.assertRaises(SchemaError):
            ledger.issue(
                make_lead(stage="checking"), self.reviewers,
                issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-T1"], evidence_sufficient=True,
            )


class LabelSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.reviewers = load_reviewers(load_fixture("reviewers.json"))
        self.ledger = LabelLedger()

    def test_unfiled_violation_is_positive_never_negative(self):
        # 核心防偏规则：确认违法但未立案仍是正样本
        self.assertEqual(OUTCOME_LABELS["violation_unfiled"], "positive")
        rec = self.ledger.issue(
            make_lead(outcome="violation_unfiled"), self.reviewers,
            issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
            source="field_check", evidence_ids=["EV-T2"], evidence_sufficient=True,
        )
        self.assertEqual(rec["label"], "positive")

    def test_insufficient_evidence_cannot_become_negative(self):
        # “未立案/证据暂缺”一律当负样本正是要堵的漏洞
        with self.assertRaises(LabelError):
            self.ledger.issue(
                make_lead(outcome="insufficient_evidence"), self.reviewers,
                issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-PARTIAL"],
                evidence_sufficient=False,
            )

    def test_evidence_required_for_stable_label(self):
        with self.assertRaises(LabelError):
            self.ledger.issue(
                make_lead(outcome="legal_exception"), self.reviewers,
                issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=[], evidence_sufficient=True,
            )
        with self.assertRaises(LabelError):
            self.ledger.issue(
                make_lead(outcome="violation_filed"), self.reviewers,
                issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
                source="field_check", evidence_ids=["EV-T3"],
                evidence_sufficient=False,
            )

    def test_rule_self_proof_is_excluded_not_negative(self):
        rec = self.ledger.issue(
            make_lead(outcome="rule_self_proof"), self.reviewers,
            issued_by="RV-001", issued_at="2026-03-21T09:00:00+08:00",
            source="field_check", evidence_ids=["EV-RULE-ONLY"],
            evidence_sufficient=True,
        )
        self.assertEqual(rec["label"], "excluded")


class VersionFlowTest(unittest.TestCase):
    def setUp(self):
        self.reviewers = load_reviewers(load_fixture("reviewers.json"))

    def test_appeal_creates_new_version_and_supersedes(self):
        lead = make_lead(outcome="legal_exception")
        ledger = LabelLedger()
        v1 = ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-02-20T10:00:00+08:00",
            source="field_check", evidence_ids=["EV-INIT"], evidence_sufficient=True,
        )
        self.assertEqual(v1["label"], "negative")

        # 申诉调取新证据后改判：结论文档更新，标签以新版本追加而非覆盖
        lead["conclusion"] = {
            "outcome": "violation_filed",
            "reason_codes": ["appeal-upheld", "new-evidence"],
            "narrative": "申诉改判",
            "decided_at": "2026-05-25T15:00:00+08:00",
        }
        v2 = ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-05-26T15:30:00+08:00",
            source="appeal", evidence_ids=["EV-NEW-A", "EV-NEW-B"],
            evidence_sufficient=True, appeal_id="AP-TEST-1",
        )
        self.assertEqual((v2["version"], v2["label"]), (2, "positive"))
        self.assertEqual(v2["supersedes_version"], 1)
        self.assertEqual(v1["status"], "superseded")
        self.assertEqual(ledger.current(lead["lead_id"])["version"], 2)

    def test_field_check_cannot_overwrite_existing_label(self):
        lead = make_lead(outcome="legal_exception")
        ledger = LabelLedger()
        ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-02-20T10:00:00+08:00",
            source="field_check", evidence_ids=["EV-INIT"], evidence_sufficient=True,
        )
        with self.assertRaises(LabelError):
            ledger.issue(
                lead, self.reviewers,
                issued_by="RV-001", issued_at="2026-03-01T10:00:00+08:00",
                source="field_check", evidence_ids=["EV-MORE"], evidence_sufficient=True,
            )

    def test_appeal_requires_appeal_id(self):
        lead = make_lead(outcome="legal_exception")
        ledger = LabelLedger()
        ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-02-20T10:00:00+08:00",
            source="field_check", evidence_ids=["EV-INIT"], evidence_sufficient=True,
        )
        with self.assertRaises(LabelError):
            ledger.issue(
                lead, self.reviewers,
                issued_by="RV-001", issued_at="2026-05-26T10:00:00+08:00",
                source="appeal", evidence_ids=["EV-NEW"], evidence_sufficient=True,
            )

    def test_case_outcome_requires_case_ref(self):
        lead = make_lead(outcome="violation_filed")
        ledger = LabelLedger()
        ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-02-20T10:00:00+08:00",
            source="field_check", evidence_ids=["EV-INIT"], evidence_sufficient=True,
        )
        with self.assertRaises(LabelError):
            ledger.issue(
                lead, self.reviewers,
                issued_by="RV-001", issued_at="2026-06-01T10:00:00+08:00",
                source="case_outcome", evidence_ids=["EV-CASE"], evidence_sufficient=True,
            )

    def test_revoke_leaves_no_current_label(self):
        lead = make_lead(outcome="violation_filed")
        ledger = LabelLedger()
        ledger.issue(
            lead, self.reviewers,
            issued_by="RV-001", issued_at="2026-05-18T09:00:00+08:00",
            source="field_check", evidence_ids=["EV-BAD"], evidence_sufficient=True,
        )
        revoked = ledger.revoke(
            lead["lead_id"], revoked_at="2026-05-28T16:00:00+08:00",
            reason="主体串档，依据错误",
        )
        self.assertEqual(revoked["status"], "revoked")
        self.assertIsNone(ledger.current(lead["lead_id"]))
        self.assertEqual(ledger.latest(lead["lead_id"])["status"], "revoked")


class FixtureLedgerTest(unittest.TestCase):
    def test_fixture_label_versions_load(self):
        leads = load_leads(load_fixture("leads.json"))
        self.assertEqual(len(leads), 18)
        ledger = LabelLedger(load_fixture("labels.json"))
        current_1012 = ledger.current("L-2026-1012")
        self.assertEqual((current_1012["version"], current_1012["label"]), (2, "positive"))
        self.assertEqual(current_1012["basis"]["source"], "appeal")


if __name__ == "__main__":
    unittest.main()
