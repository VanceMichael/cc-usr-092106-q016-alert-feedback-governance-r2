"""训练用脱敏快照：明确时间切分，排除不稳定记录。

不得混入稳定标签的记录：
- 尚未结案；
- 跨区域重复；
- 规则自证（结论仅由触发规则自身逻辑得出）；
- 数据错误；
- 未签发标签；
- 超出时间切分范围。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from .labels import LabelBook, LabelValue
from .leads import Conclusion, Lead


class ExclusionReason(str, Enum):
    NOT_CLOSED = "not_closed"  # 尚未结案
    DATA_ERROR = "data_error"  # 数据错误
    CROSS_REGION_DUPLICATE = "cross_region_duplicate"  # 跨区域重复
    SELF_PROVING = "self_proving"  # 规则自证
    NO_LABEL = "no_label"  # 未签发稳定标签
    AFTER_CUTOFF = "after_cutoff"  # 超出时间切分


# 排除检查的先后顺序：每条线索只记录第一个命中的排除原因。
_EXCLUSION_ORDER = (
    ExclusionReason.NOT_CLOSED,
    ExclusionReason.DATA_ERROR,
    ExclusionReason.CROSS_REGION_DUPLICATE,
    ExclusionReason.SELF_PROVING,
    ExclusionReason.NO_LABEL,
    ExclusionReason.AFTER_CUTOFF,
)


@dataclass(frozen=True)
class SnapshotRecord:
    """脱敏后的训练记录：不含原始对象标识与线索编号。"""

    lead_ref: str  # 加盐哈希后的线索标识
    subject_hash: str  # 加盐哈希后的监管对象标识
    region: str
    trigger_key: str
    label: LabelValue
    label_version: int
    split: str  # "train" 或 "validation"
    closed_at: datetime


@dataclass(frozen=True)
class Exclusion:
    lead_id: str
    reason: ExclusionReason


@dataclass
class Snapshot:
    """一个带时间切分的脱敏训练快照。"""

    train_end: date
    validation_end: date
    records: list[SnapshotRecord] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)

    def usable(self, split: str | None = None) -> list[SnapshotRecord]:
        if split is None:
            return list(self.records)
        return [r for r in self.records if r.split == split]

    def exclusions_by_reason(self) -> dict[ExclusionReason, int]:
        counts: dict[ExclusionReason, int] = {}
        for item in self.exclusions:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def _exclusion_reason(
    lead: Lead, label_book: LabelBook, validation_end: date
) -> ExclusionReason | None:
    if not lead.is_closed:
        return ExclusionReason.NOT_CLOSED
    if lead.conclusion is Conclusion.DATA_ERROR:
        return ExclusionReason.DATA_ERROR
    if lead.duplicate_of is not None:
        return ExclusionReason.CROSS_REGION_DUPLICATE
    if lead.self_proving:
        return ExclusionReason.SELF_PROVING
    if label_book.current(lead.lead_id) is None:
        return ExclusionReason.NO_LABEL
    assert lead.closed_at is not None
    if lead.closed_at.date() > validation_end:
        return ExclusionReason.AFTER_CUTOFF
    return None


def build_snapshot(
    leads: list[Lead],
    label_book: LabelBook,
    *,
    train_end: date,
    validation_end: date,
    salt: str,
) -> Snapshot:
    """按时间切分构建脱敏快照，并逐条记录排除原因。

    train_end 之前（含）结案的进入训练集，train_end 之后、
    validation_end 之前（含）结案的进入验证集。
    """
    if train_end > validation_end:
        raise ValueError("train_end 不能晚于 validation_end")
    snapshot = Snapshot(train_end=train_end, validation_end=validation_end)
    for lead in leads:
        reason = _exclusion_reason(lead, label_book, validation_end)
        if reason is not None:
            snapshot.exclusions.append(Exclusion(lead.lead_id, reason))
            continue
        label = label_book.current(lead.lead_id)
        assert label is not None and lead.closed_at is not None
        split = (
            "train" if lead.closed_at.date() <= train_end else "validation"
        )
        snapshot.records.append(
            SnapshotRecord(
                lead_ref=_hash(salt, lead.lead_id),
                subject_hash=_hash(salt, lead.subject_ref),
                region=lead.region,
                trigger_key=lead.trigger.key,
                label=label.value,
                label_version=label.version,
                split=split,
                closed_at=lead.closed_at,
            )
        )
    return snapshot


def _hash(salt: str, raw: str) -> str:
    return hashlib.sha256(f"{salt}:{raw}".encode("utf-8")).hexdigest()[:16]
