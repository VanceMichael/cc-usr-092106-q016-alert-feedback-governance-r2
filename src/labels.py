"""标签签发簿：权限守卫、证据门控、版本流转（申诉/案件结果形成新版本）。"""

from __future__ import annotations

from .contracts import validate_contract
from .reviewers import assert_can_issue
from .leads import require_concluded

# 核查结论到训练标签的映射；None 表示该结论在治理策略下根本不签发标签
OUTCOME_LABELS = {
    "violation_filed": "positive",     # 已立案
    "violation_unfiled": "positive",   # 确认违法但未立案——仍是正样本，不能因为“未立案”就当负样本
    "legal_exception": "negative",     # 合法例外：经充分核查的阴性
    "data_error": "negative",          # 数据错误更正：触发前提不成立的阴性
    "insufficient_evidence": None,     # 证据暂缺：不签发，补证后再走新版本
    "rule_self_proof": "excluded",     # 规则自证：用规则产出的结论反过来证明规则
    "duplicate_pending": "excluded",   # 跨区域重复待主办区域裁决
    "pending": None,                   # 尚未完成：不得形成任何标签
}

# 稳定标签（可进入训练快照）只包含 positive/negative，且必须证据充分
STABLE_LABELS = frozenset({"positive", "negative"})


class LabelError(ValueError):
    """签发不满足治理规则。"""


class LabelLedger:
    """同一线索的标签版本历史，内存表示；持久化时按 lead_id 分区追加。"""

    def __init__(self, records: list[dict] | None = None):
        self._records: list[dict] = []
        for rec in records or []:
            self.import_record(rec)

    # -- 读取 -------------------------------------------------------------

    @property
    def records(self) -> list[dict]:
        return sorted(self._records, key=lambda r: (r["lead_id"], r["version"]))

    def for_lead(self, lead_id: str) -> list[dict]:
        return [r for r in self._records if r["lead_id"] == lead_id]

    def current(self, lead_id: str) -> dict | None:
        issued = [r for r in self.for_lead(lead_id) if r["status"] == "issued"]
        return max(issued, key=lambda r: r["version"], default=None)

    def latest(self, lead_id: str) -> dict | None:
        """返回最新版本记录，不论状态（用于识别撤销等情形）。"""
        records = self.for_lead(lead_id)
        return max(records, key=lambda r: r["version"], default=None)

    def import_record(self, record: dict) -> dict:
        validate_contract("label", record)
        self._records.append(record)
        return record

    # -- 签发 -------------------------------------------------------------

    def issue(
        self,
        lead: dict,
        reviewers: dict[str, dict],
        *,
        issued_by: str,
        issued_at: str,
        source: str,
        evidence_ids: list[str],
        evidence_sufficient: bool,
        appeal_id: str | None = None,
        case_ref: str | None = None,
    ) -> dict:
        """按线索结论签发新版本标签。

        守卫顺序：权限 → 已结案 → 结论可取 → 证据门控 → 版本一致性。
        """
        conclusion = require_concluded(lead)
        assert_can_issue(reviewers, issued_by, lead["region_code"])

        outcome = conclusion["outcome"]
        label = OUTCOME_LABELS[outcome]
        if label is None:
            reason = {
                "insufficient_evidence": (
                    "证据暂缺：不签发任何标签（含 excluded）。该线索由结论在快照阶段直接排除，"
                    "补证后再按新版本签发；“未立案/证据暂缺”绝不能回流为负样本"
                ),
                "pending": "尚未完成核查，不得形成任何标签",
            }[outcome]
            raise LabelError(f"线索 {lead['lead_id']} {reason}")
        if not evidence_ids:
            raise LabelError(f"线索 {lead['lead_id']} 缺少证据材料登记号，不得签发")
        if not evidence_sufficient and label in STABLE_LABELS:
            raise LabelError(
                f"线索 {lead['lead_id']} 证据不充分时不得签发 {label} 稳定标签"
                + ("（“未立案/证据暂缺”不能直接当作负样本）" if outcome == "insufficient_evidence" else "")
            )
        if source == "appeal" and not appeal_id:
            raise LabelError("申诉来源必须登记 appeal_id")
        if source == "case_outcome" and not case_ref:
            raise LabelError("案件结果来源必须登记 case_ref")

        prior = self.current(lead["lead_id"])
        version = 1 if prior is None else prior["version"] + 1
        if prior is not None and source == "field_check":
            raise LabelError(
                f"线索 {lead['lead_id']} 已存在生效标签 v{prior['version']}；"
                "新结论只能通过申诉(appeal)或案件结果(case_outcome)形成新版本"
            )

        record = validate_contract("label", {
            "lead_id": lead["lead_id"],
            "version": version,
            "label": label,
            "basis": {
                "outcome": outcome,
                "evidence_ids": list(evidence_ids),
                "evidence_sufficient": evidence_sufficient,
                "source": source,
                "appeal_id": appeal_id,
                "case_ref": case_ref,
            },
            "issued_by": issued_by,
            "issued_at": issued_at,
            "supersedes_version": None if prior is None else prior["version"],
            "status": "issued",
        })
        if prior is not None:
            prior["status"] = "superseded"
        self._records.append(record)
        return record

    def revoke(self, lead_id: str, *, revoked_at: str, reason: str) -> dict:
        """发现签发错误时撤销当前版本；撤销原因进入审计（reason 仅用于调用方留痕）。"""
        current = self.current(lead_id)
        if current is None:
            raise LabelError(f"线索 {lead_id} 没有可撤销的生效标签")
        current["status"] = "revoked"
        current["revoked_at"] = revoked_at
        current["revoke_reason"] = reason
        validate_contract("label", current)
        return current
