import unittest

from src.monitoring import (
    load_deployments, load_metrics, compare_deployment, window_stats,
)

from tests.support import load_fixture


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.deployment = load_deployments(
            load_fixture("deployments.json"))[0]
        self.metrics = load_metrics(load_fixture("metrics.json"))

    def test_pre_post_counts_and_burden_delta(self):
        report = compare_deployment(self.metrics, self.deployment)
        pre, post = report["pre"], report["post"]

        self.assertEqual(pre["hit_count"], 6)
        self.assertEqual(post["hit_count"], 4)
        # 新规则上线后命中量与人工总量下降
        self.assertLess(post["hit_count"], pre["hit_count"])
        self.assertLess(post["total_review_minutes"],
                        pre["total_review_minutes"])
        self.assertEqual(report["delta"]["hit_count"], -2)
        # post 窗口出现免人工复核线索，人工率下降
        self.assertLess(post["manual_review_rate"], pre["manual_review_rate"])

    def test_positive_rate_computed_on_labeled_only(self):
        report = compare_deployment(self.metrics, self.deployment)
        # pre：有正负标签的 3 条中 positive 2 条（excluded、撤销/未结不计入分母）
        self.assertEqual(report["pre"]["positive_rate"], round(2 / 3, 4))
        # post：已标签 3 条中 positive 1 条
        self.assertEqual(report["post"]["positive_rate"], round(1 / 3, 4))

    def test_window_stats_lead_ids_enable_drilldown(self):
        stats = window_stats(load_metrics(load_fixture("metrics.json"))["lead_hits"])
        self.assertIn("L-2026-1007", stats["lead_ids"])

    def test_misassigned_window_rejected(self):
        bad = load_fixture("metrics.json")
        bad["lead_hits"][0]["window"] = "post"  # 5 月命中却被标成上线后
        with self.assertRaises(ValueError):
            compare_deployment(load_metrics(bad), self.deployment)

    def test_deployment_mismatch_rejected(self):
        other = dict(self.deployment)
        other["deployment_id"] = "D-OTHER"
        with self.assertRaises(ValueError):
            compare_deployment(self.metrics, other)


if __name__ == "__main__":
    unittest.main()
