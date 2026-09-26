"""反馈标签的签发、申诉与版本管理。

治理原则：
- 标签只能由具备权限的复核者在证据充分时签发；
- “未立案”中的证据暂缺、尚未完成、数据错误不能形成标签；
- 申诉或后续案件结果形成新版本，历史版本不可改写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .leads import Conclusion, Lead

SIGNER_ROLE = "label-signer"


class LabelAuthorizationError(PermissionError):
    """复核者不具备签发权限。"""


class EvidenceInsufficientError(ValueError):
    """证据不充分，不能签发标签。"""


class UnresolvableConclusionError(ValueError):
    """当前结论无法形成稳定标签（证据暂缺/尚未完成/数据错误）。"""


class LabelValue(str, Enum):
    POSITIVE = "positive"  # 确认风险
    NEGATIVE = "negative"  # 排除风险


class LabelSource(str, Enum):
    REVIEW = "review"  # 复核签发
    APPEAL = "appeal"  # 申诉改判
    CASE_OUTCOME = "case_outcome"  # 后续案件结果


# 只有确定性的核查结论才能映射为标签；其余“未立案”情形一律不可签发。
CONCLUSION_TO_LABEL = {
    Conclusion.FILED: LabelValue.POSITIVE,
    Conclusion.LEGAL_EXCEPTION: LabelValue.NEGATIVE,
}


@dataclass(frozen=True)
class Reviewer:
    """复核者：须持有签发角色且被授权到线索所在区域。"""

    reviewer_id: str
    roles: frozenset[str]
    regions: frozenset[str]


@dataclass(frozen=True)
class LabelVersion:
    """标签的一个不可变版本，含完整签发依据。"""

    version: int
    value: LabelValue
    issued_by: str
    issued_at: datetime
    evidence_refs: tuple[str, ...]
    basis: str  # 签发依据说明
    source: LabelSource


@dataclass
class LabelRecord:
    """一条线索的标签版本链。"""

    lead_id: str
    history: list[LabelVersion] = field(default_factory=list)

    @property
    def current(self) -> LabelVersion:
        return self.history[-1]


class LabelBook:
    """标签台账：签发、申诉与案件结果登记。"""

    def __init__(self) -> None:
        self._records: dict[str, LabelRecord] = {}

    def current(self, lead_id: str) -> LabelVersion | None:
        record = self._records.get(lead_id)
        return record.current if record and record.history else None

    def history(self, lead_id: str) -> list[LabelVersion]:
        record = self._records.get(lead_id)
        return list(record.history) if record else []

    def issue(
        self,
        lead: Lead,
        reviewer: Reviewer,
        *,
        issued_at: datetime,
        evidence_refs: list[str],
        basis: str,
    ) -> LabelVersion:
        """首次签发标签，取值由结构化结论推导。"""
        if self.current(lead.lead_id) is not None:
            raise ValueError(f"线索 {lead.lead_id} 已有标签，应通过申诉形成新版本")
        self._check_reviewer(lead, reviewer)
        self._check_evidence(lead, evidence_refs, basis)
        value = CONCLUSION_TO_LABEL[lead.conclusion]
        return self._append(
            lead.lead_id, value, reviewer.reviewer_id, issued_at,
            evidence_refs, basis, LabelSource.REVIEW,
        )

    def appeal(
        self,
        lead: Lead,
        reviewer: Reviewer,
        *,
        value: LabelValue,
        issued_at: datetime,
        evidence_refs: list[str],
        basis: str,
    ) -> LabelVersion:
        """申诉改判：在既有标签上形成新版本。"""
        if self.current(lead.lead_id) is None:
            raise ValueError(f"线索 {lead.lead_id} 尚无已签发标签，不能申诉")
        self._check_reviewer(lead, reviewer)
        self._check_evidence(lead, evidence_refs, basis)
        return self._append(
            lead.lead_id, value, reviewer.reviewer_id, issued_at,
            evidence_refs, basis, LabelSource.APPEAL,
        )

    def record_case_outcome(
        self,
        lead: Lead,
        *,
        case_ref: str,
        value: LabelValue,
        recorded_at: datetime,
        basis: str,
    ) -> LabelVersion:
        """后续案件结果登记为新版本（系统来源，依据为案件编号）。"""
        if self.current(lead.lead_id) is None:
            raise ValueError(f"线索 {lead.lead_id} 尚无已签发标签，不能登记案件结果")
        if not basis:
            raise EvidenceInsufficientError("必须填写签发依据")
        return self._append(
            lead.lead_id, value, f"case:{case_ref}", recorded_at,
            [case_ref], basis, LabelSource.CASE_OUTCOME,
        )

    def _append(
        self,
        lead_id: str,
        value: LabelValue,
        issued_by: str,
        issued_at: datetime,
        evidence_refs: list[str],
        basis: str,
        source: LabelSource,
    ) -> LabelVersion:
        record = self._records.setdefault(lead_id, LabelRecord(lead_id))
        version = LabelVersion(
            version=len(record.history) + 1,
            value=value,
            issued_by=issued_by,
            issued_at=issued_at,
            evidence_refs=tuple(evidence_refs),
            basis=basis,
            source=source,
        )
        record.history.append(version)
        return version

    @staticmethod
    def _check_reviewer(lead: Lead, reviewer: Reviewer) -> None:
        if SIGNER_ROLE not in reviewer.roles:
            raise LabelAuthorizationError(
                f"复核者 {reviewer.reviewer_id} 不具备签发角色"
            )
        if lead.region not in reviewer.regions:
            raise LabelAuthorizationError(
                f"复核者 {reviewer.reviewer_id} 未被授权到区域 {lead.region}"
            )

    @staticmethod
    def _check_evidence(
        lead: Lead, evidence_refs: list[str], basis: str
    ) -> None:
        if not lead.is_closed:
            raise EvidenceInsufficientError(
                f"线索 {lead.lead_id} 尚未结案，不能签发标签"
            )
        if lead.conclusion not in CONCLUSION_TO_LABEL:
            raise UnresolvableConclusionError(
                f"线索 {lead.lead_id} 结论为 {lead.conclusion}，"
                "属于证据暂缺/尚未完成/数据错误，不能当作负样本或正样本"
            )
        if not evidence_refs:
            raise EvidenceInsufficientError("签发标签必须引用证据材料")
        if not basis:
            raise EvidenceInsufficientError("必须填写签发依据")
