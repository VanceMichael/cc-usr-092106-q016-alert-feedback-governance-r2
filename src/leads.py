"""线索数据装载与阶段判定。"""

from __future__ import annotations

from .contracts import validate_contract
from .validation import SchemaError
from .timeutil import parse_dt

# 尚未结案的核查阶段
OPEN_STAGES = frozenset({"new", "assigned", "checking"})
CLOSED_STAGES = frozenset({"concluded", "appealed", "closed"})


def load_leads(documents: list[dict]) -> list[dict]:
    """校验并返回线索列表，按创建时间排序。"""
    leads = [validate_contract("lead", d) for d in documents]
    return sorted(leads, key=lambda x: parse_dt(x["created_at"]))


def is_open(lead: dict) -> bool:
    return lead["stage"] in OPEN_STAGES


def get_conclusion(lead: dict) -> dict | None:
    return lead.get("conclusion")


def require_concluded(lead: dict) -> dict:
    """签发稳定标签前，线索必须已有结构化结论。"""
    if is_open(lead):
        raise SchemaError(f"线索 {lead['lead_id']} 尚未结案（阶段 {lead['stage']}），不得签发稳定标签")
    conclusion = lead.get("conclusion")
    if conclusion is None:
        raise SchemaError(f"线索 {lead['lead_id']} 缺少结构化结论")
    return conclusion
