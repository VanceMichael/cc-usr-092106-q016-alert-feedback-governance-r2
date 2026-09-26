"""线索台账：记录触发来源、输入数据水位、分派范围与核查结论。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReviewStage(str, Enum):
    """核查阶段。"""

    DISPATCHED = "dispatched"  # 已分派
    IN_REVIEW = "in_review"  # 核查中
    PENDING_SIGNOFF = "pending_signoff"  # 待复核
    CLOSED = "closed"  # 已结案


class Conclusion(str, Enum):
    """结构化核查结论。

    “未立案”不是单一含义：证据暂缺、合法例外、数据错误与尚未完成
    必须分开记录，不能一概当作负样本。
    """

    FILED = "filed"  # 立案
    EVIDENCE_PENDING = "evidence_pending"  # 未立案：证据暂缺
    LEGAL_EXCEPTION = "legal_exception"  # 未立案：合法例外
    DATA_ERROR = "data_error"  # 数据错误
    INCOMPLETE = "incomplete"  # 尚未完成


@dataclass(frozen=True)
class Trigger:
    """触发来源：规则或模型及其版本，含输入数据水位。"""

    kind: str  # "rule" 或 "model"
    identifier: str
    version: str
    data_watermark: datetime  # 触发时输入数据水位

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.identifier}@{self.version}"


@dataclass
class Lead:
    """一条核查线索的完整台账记录。"""

    lead_id: str
    subject_ref: str  # 监管对象标识（仅台账内部保存，对外输出须脱敏）
    region: str
    trigger: Trigger
    assigned_org: str  # 分派范围
    stage: ReviewStage = ReviewStage.DISPATCHED
    conclusion: Conclusion | None = None
    closed_at: datetime | None = None
    evidence_refs: list[str] = field(default_factory=list)  # 证据材料编号
    self_proving: bool = False  # 结论仅由触发规则自身逻辑得出（规则自证）
    duplicate_of: str | None = None  # 跨区域重复时指向主线索
    effort_hours: float = 0.0  # 累计核查人工时长

    @property
    def is_closed(self) -> bool:
        return self.stage is ReviewStage.CLOSED

    def close(
        self,
        conclusion: Conclusion,
        closed_at: datetime,
        *,
        evidence_refs: list[str] | None = None,
        effort_hours: float = 0.0,
        self_proving: bool = False,
    ) -> None:
        """录入核查结论并结案。"""
        if self.is_closed:
            raise ValueError(f"线索 {self.lead_id} 已结案，不能重复结案")
        self.stage = ReviewStage.CLOSED
        self.conclusion = conclusion
        self.closed_at = closed_at
        if evidence_refs:
            self.evidence_refs = list(evidence_refs)
        self.effort_hours += effort_hours
        self.self_proving = self_proving
