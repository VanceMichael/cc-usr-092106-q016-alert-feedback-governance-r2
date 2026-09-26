"""批次治理报告：说明反馈为何可用、哪些被排除、新规则改变了什么。"""

from __future__ import annotations

from dataclasses import dataclass

from .labels import LabelBook, LabelVersion
from .leads import Lead
from .metrics import VersionMetrics, collect_metrics
from .snapshots import ExclusionReason, Snapshot, build_snapshot


@dataclass(frozen=True)
class VersionDiff:
    """两个触发版本之间的命中分布与人工负担变化。"""

    old_key: str
    new_key: str
    delta_hits: int
    delta_positive_rate: float
    delta_hours_per_hit: float
    delta_open_leads: int


@dataclass
class BatchReport:
    """一批反馈的可用性说明，模型负责人与审计人员共用。"""

    snapshot: Snapshot
    metrics: dict[str, VersionMetrics]
    label_book: LabelBook

    def usable_count(self, split: str | None = None) -> int:
        return len(self.snapshot.usable(split))

    def excluded_count(self, reason: ExclusionReason | None = None) -> int:
        if reason is None:
            return len(self.snapshot.exclusions)
        return self.snapshot.exclusions_by_reason().get(reason, 0)

    def explain(self) -> str:
        """说明本批反馈为何可用、哪些被排除。"""
        lines = [
            f"训练集 {self.usable_count('train')} 条，"
            f"验证集 {self.usable_count('validation')} 条，"
            f"排除 {self.excluded_count()} 条。"
        ]
        for reason, count in sorted(
            self.snapshot.exclusions_by_reason().items(), key=lambda kv: kv[0].value
        ):
            lines.append(f"排除原因 {reason.value}: {count} 条")
        return "\n".join(lines)

    def audit_trail(self, trigger_key: str) -> list[LabelVersion]:
        """从指标回到具体签发依据：该版本指标涉及的全部标签版本。"""
        row = self.metrics.get(trigger_key)
        if row is None:
            raise KeyError(f"没有触发版本 {trigger_key} 的指标")
        trail: list[LabelVersion] = []
        for contributor in row.contributors:
            if contributor.label_version is None:
                continue
            history = self.label_book.history(contributor.lead_id)
            trail.append(history[contributor.label_version - 1])
        return trail

    def version_diff(self, old_key: str, new_key: str) -> VersionDiff:
        """比较新旧规则/模型版本：命中量、阳性率与人工负担的变化。"""
        old = self.metrics[old_key]
        new = self.metrics[new_key]
        return VersionDiff(
            old_key=old_key,
            new_key=new_key,
            delta_hits=new.total_hits - old.total_hits,
            delta_positive_rate=new.positive_rate - old.positive_rate,
            delta_hours_per_hit=new.hours_per_hit - old.hours_per_hit,
            delta_open_leads=new.open_leads - old.open_leads,
        )


def build_batch_report(
    leads: list[Lead],
    label_book: LabelBook,
    *,
    train_end,
    validation_end,
    salt: str,
) -> BatchReport:
    """一次性生成快照、指标与可审计的批次报告。"""
    snapshot = build_snapshot(
        leads,
        label_book,
        train_end=train_end,
        validation_end=validation_end,
        salt=salt,
    )
    metrics = collect_metrics(leads, label_book)
    return BatchReport(snapshot=snapshot, metrics=metrics, label_book=label_book)
