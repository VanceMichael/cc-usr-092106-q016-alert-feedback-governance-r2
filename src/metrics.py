"""版本上线后的命中分布与人工负担追踪。

每个指标行都保留贡献者（线索 + 标签版本）引用，
审计人员可以从指标回到具体签发依据。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .labels import LabelBook, LabelValue
from .leads import Conclusion, Lead


@dataclass(frozen=True)
class MetricContributor:
    """指标的可回溯来源：线索及其计入时使用的标签版本。"""

    lead_id: str
    label_version: int | None


@dataclass
class VersionMetrics:
    """某个规则/模型版本的命中分布与人工负担。"""

    trigger_key: str
    total_hits: int = 0
    by_conclusion: dict[Conclusion, int] = field(default_factory=dict)
    by_label: dict[LabelValue, int] = field(default_factory=dict)
    open_leads: int = 0  # 尚未结案的在办量
    effort_hours: float = 0.0
    contributors: list[MetricContributor] = field(default_factory=list)

    @property
    def hours_per_hit(self) -> float:
        """单条命中的平均人工负担。"""
        if self.total_hits == 0:
            return 0.0
        return self.effort_hours / self.total_hits

    @property
    def positive_rate(self) -> float:
        """已签发标签中的阳性占比。"""
        labeled = sum(self.by_label.values())
        if labeled == 0:
            return 0.0
        return self.by_label.get(LabelValue.POSITIVE, 0) / labeled


def collect_metrics(
    leads: list[Lead], label_book: LabelBook
) -> dict[str, VersionMetrics]:
    """按触发版本汇总命中分布与人工负担。"""
    metrics: dict[str, VersionMetrics] = {}
    for lead in leads:
        key = lead.trigger.key
        row = metrics.setdefault(key, VersionMetrics(trigger_key=key))
        row.total_hits += 1
        row.effort_hours += lead.effort_hours
        label = label_book.current(lead.lead_id)
        if lead.is_closed and lead.conclusion is not None:
            row.by_conclusion[lead.conclusion] = (
                row.by_conclusion.get(lead.conclusion, 0) + 1
            )
        else:
            row.open_leads += 1
        if label is not None:
            row.by_label[label.value] = row.by_label.get(label.value, 0) + 1
        row.contributors.append(
            MetricContributor(
                lead_id=lead.lead_id,
                label_version=label.version if label else None,
            )
        )
    return metrics
