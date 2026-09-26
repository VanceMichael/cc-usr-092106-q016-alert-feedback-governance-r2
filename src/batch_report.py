"""快照批次说明：模型负责人说明某批反馈为何可用、哪些被排除。"""

from __future__ import annotations

from collections import Counter

from .contracts import validate_contract
from .eligibility import EXCLUSION_REASONS


def build_batch_report(
    snapshot: dict,
    *,
    prepared_by: str,
    prepared_at: str,
    attestation: str,
    rationale: str | None = None,
) -> dict:
    """由快照排除清单聚合生成批次说明，排除计数必须与快照逐码一致。"""
    counter = Counter(item["exclusion_code"] for item in snapshot["excluded"])
    exclusion_summary = [
        {
            "exclusion_code": code,
            "count": count,
            "reason": EXCLUSION_REASONS[code],
        }
        for code, count in sorted(counter.items())
    ]

    manifest = snapshot["manifest"]
    usable = manifest["included_count"] > 0
    if rationale is None:
        rationale = (
            f"快照 {snapshot['snapshot_id']} 以 {snapshot['cutoff']} 为标签水位，"
            f"仅纳入证据充分且经过 {snapshot['min_label_settled_days']} 天冷静期的稳定标签；"
            "按标签稳定时间做 train/validation/test 切分，同一主体不跨分区；"
            "主体标识加盐假名化、区域下沉为大区桶、时间按月取整。"
        )

    report = {
        "snapshot_id": snapshot["snapshot_id"],
        "prepared_by": prepared_by,
        "prepared_at": prepared_at,
        "usable": usable,
        "rationale": rationale,
        "exclusion_summary": exclusion_summary,
        "attestation": attestation,
    }
    return validate_contract("batch_report", report)
