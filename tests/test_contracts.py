import unittest

from src.contracts import validate_contract
from src.validation import SchemaError

from tests.support import load_fixture


class ContractTest(unittest.TestCase):
    def test_all_fixtures_match_contracts(self):
        validate_contract("lead", load_fixture("leads.json")[0])
        validate_contract("reviewer", load_fixture("reviewers.json"))
        for rec in load_fixture("labels.json"):
            validate_contract("label", rec)
        validate_contract("snapshot", load_fixture("snapshot.json"))
        validate_contract("deployment", load_fixture("deployments.json"))
        validate_contract("metrics", load_fixture("metrics.json"))
        validate_contract("batch_report", load_fixture("batch_report.json"))

    def test_missing_required_field_rejected(self):
        bad = {"lead_id": "X"}
        with self.assertRaises(SchemaError):
            validate_contract("lead", bad)

    def test_unknown_field_rejected(self):
        doc = load_fixture("leads.json")[0].copy()
        doc["unexpected"] = 1
        with self.assertRaises(SchemaError):
            validate_contract("lead", doc)

    def test_bad_datetime_rejected(self):
        doc = load_fixture("leads.json")[0].copy()
        doc["created_at"] = "2026-02-20 08:00:00"  # 缺时区且非 ISO
        with self.assertRaises(SchemaError):
            validate_contract("lead", doc)


if __name__ == "__main__":
    unittest.main()
