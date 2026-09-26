"""契约加载：按名称读取 contracts/*.schema.json 并校验文档。"""

from __future__ import annotations

import json
from pathlib import Path

from .validation import validate

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contracts"

_CONTRACTS = {
    "context": "context.schema.json",
    "lead": "lead.schema.json",
    "reviewer": "reviewer.schema.json",
    "label": "label.schema.json",
    "snapshot": "snapshot.schema.json",
    "deployment": "deployment.schema.json",
    "metrics": "metrics.schema.json",
    "batch_report": "batch_report.schema.json",
}


def load_schema(name: str) -> dict:
    return json.loads((CONTRACT_DIR / _CONTRACTS[name]).read_text(encoding="utf-8"))


def validate_contract(name: str, document: dict) -> dict:
    validate(document, load_schema(name))
    return document
