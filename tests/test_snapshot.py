import unittest

from src.leads import load_leads
from src.reviewers import load_reviewers
from src.labels import LabelLedger
from src.snapshot import build_snapshot, pseudonymize, region_bucket
from src.batch_report import build_batch_report

from tests.support import load_fixture

BUCKETS = {
    "11": "north", "12": "north",
    "31": "east", "32": "east", "33": "east",
    "42": "central",
    "44": "south",
    "51": "southwest", "61": "northwest",
}

SPLIT = {
    "train_end": "2026-04-01T00:00:00+08:00",
    "validation_end": "2026-06-01T00:00:00+08:00",
}


def build_fixture_snapshot(**overrides):
    params = dict(
        snapshot_id="snap-test",
        created_at="2026-07-01T10:00:00+08:00",
        cutoff="2026-07-01T00:00:00+08:00",
        split=SPLIT,
        min_settled_days=14,
        leads=load_leads(load_fixture("leads.json")),
        ledger=LabelLedger(load_fixture("labels.json")),
        salt="unit-test-salt",
        province_buckets=BUCKETS,
    )
    params.update(overrides)
    return build_snapshot(**params)


class SnapshotExclusionTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_fixture_snapshot()
        self.excluded = {e["lead_id"]: e["exclusion_code"]
                         for e in self.snapshot["excluded"]}

    def test_unstable_cases_excluded(self):
        # 尚未结案
        self.assertEqual(self.excluded["L-2026-1010"], "open_case")
        # 证据暂缺（不能当负样本）
        self.assertEqual(self.excluded["L-2026-1004"], "insufficient_evidence")
        # 规则自证
        self.assertEqual(self.excluded["L-2026-1006"], "rule_self_proof")
        # 跨区域重复：主办保留、副本去重；待裁决组排除
        self.assertEqual(self.excluded["L-2026-1008"], "cross_region_duplicate")
        self.assertEqual(self.excluded["L-2026-1009"], "cross_region_duplicate")
        self.assertNotIn("L-2026-1007", self.excluded)
        # 撤销标签
        self.assertEqual(self.excluded["L-2026-1011"], "revoked_label")
        # 冷静期未满
        self.assertEqual(self.excluded["L-2026-1013"], "settling_window")
        # 超出水位
        self.assertEqual(self.excluded["L-2026-1014"], "outside_cutoff")
        # 证据充分性未确认的历史标签
        self.assertEqual(self.excluded["L-2026-1015"], "evidence_not_sufficient")
        # 同一主体跨分区泄漏
        self.assertEqual(self.excluded["L-2026-1017"], "duplicate_cross_split")

    def test_included_records(self):
        included = {r["lead_id"]: r for r in self.snapshot["records"]}
        self.assertEqual(set(included), {
            "L-2026-1001", "L-2026-1002", "L-2026-1003", "L-2026-1005",
            "L-2026-1007", "L-2026-1012", "L-2026-1016", "L-2026-1019",
        })

    def test_manifest_counts_match_records(self):
        m = self.snapshot["manifest"]
        self.assertEqual(m["included_count"], len(self.snapshot["records"]))
        self.assertEqual(m["excluded_count"], len(self.snapshot["excluded"]))
        self.assertEqual(
            m["included_count"] + m["excluded_count"], m["lead_count"])
        self.assertEqual(
            m["positive_count"] + m["negative_count"], m["included_count"])
        self.assertEqual(
            sum(m["split_counts"].values()), m["included_count"])

    def test_time_split_uses_settled_at(self):
        by_lead = {r["lead_id"]: r for r in self.snapshot["records"]}
        self.assertEqual(by_lead["L-2026-1001"]["split"], "train")
        self.assertEqual(by_lead["L-2026-1003"]["split"], "validation")
        self.assertEqual(by_lead["L-2026-1019"]["split"], "test")

    def test_appeal_v2_label_is_what_enters_snapshot(self):
        rec = next(r for r in self.snapshot["records"]
                   if r["lead_id"] == "L-2026-1012")
        self.assertEqual(rec["label"], "positive")
        self.assertEqual(rec["label_version"], 2)


class DeidentificationTest(unittest.TestCase):
    def test_pseudonym_is_one_way_and_salted(self):
        p1 = pseudonymize("S-001", "salt-a")
        p2 = pseudonymize("S-001", "salt-b")
        p3 = pseudonymize("S-001", "salt-a")
        self.assertNotIn("S-001", p1)
        self.assertNotEqual(p1, p2)      # 换盐即换名
        self.assertEqual(p1, p3)         # 同盐确定性，可做跨表对齐

    def test_region_is_bucketed(self):
        self.assertEqual(region_bucket("110101", BUCKETS), "north")
        self.assertEqual(region_bucket("440103", BUCKETS), "south")

    def test_snapshot_has_no_raw_identifiers(self):
        snapshot = build_fixture_snapshot()
        raw = str(snapshot)
        for forbidden in ("S-001", "S-002", "110101", "310101", "EV-1001"):
            self.assertNotIn(forbidden, raw)

    def test_different_salt_changes_pseudonyms(self):
        a = build_fixture_snapshot(salt="salt-a")
        b = build_fixture_snapshot(salt="salt-b")
        names_a = {r["subject_pseudonym"] for r in a["records"]}
        names_b = {r["subject_pseudonym"] for r in b["records"]}
        self.assertTrue(names_a.isdisjoint(names_b))


class SettlingWindowTest(unittest.TestCase):
    def test_longer_window_excludes_more(self):
        s14 = build_fixture_snapshot(min_settled_days=14)
        s60 = build_fixture_snapshot(min_settled_days=60)
        self.assertLess(s60["manifest"]["included_count"],
                        s14["manifest"]["included_count"])
        codes60 = {e["exclusion_code"] for e in s60["excluded"]}
        self.assertIn("settling_window", codes60)


class BatchReportTest(unittest.TestCase):
    def test_report_counts_match_snapshot(self):
        snapshot = build_fixture_snapshot()
        report = build_batch_report(
            snapshot,
            prepared_by="模型负责人（虚构）",
            prepared_at="2026-07-01T11:00:00+08:00",
            attestation="声明确认",
        )
        summarized = sum(item["count"] for item in report["exclusion_summary"])
        self.assertEqual(summarized, snapshot["manifest"]["excluded_count"])
        codes = {item["exclusion_code"] for item in report["exclusion_summary"]}
        self.assertEqual(codes, {e["exclusion_code"] for e in snapshot["excluded"]})
        self.assertTrue(report["usable"])

    def test_empty_snapshot_is_not_usable(self):
        # 水位取到所有标签之前：没有任何稳定标签
        snapshot = build_fixture_snapshot(cutoff="2025-01-01T00:00:00+08:00")
        self.assertEqual(snapshot["manifest"]["included_count"], 0)
        report = build_batch_report(
            snapshot,
            prepared_by="模型负责人（虚构）",
            prepared_at="2026-07-01T11:00:00+08:00",
            attestation="无可用记录",
        )
        self.assertFalse(report["usable"])


if __name__ == "__main__":
    unittest.main()
