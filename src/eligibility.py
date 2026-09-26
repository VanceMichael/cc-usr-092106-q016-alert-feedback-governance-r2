"""稳定标签资格判定：哪些线索反馈能进入训练快照、哪些必须排除及原因。"""

from __future__ import annotations

from dataclasses import dataclass

from .leads import is_open
from .timeutil import add_days

# 排除码 -> 面向模型负责人的人类可读说明
EXCLUSION_REASONS = {
    "open_case": "线索尚未结案，结论可能继续变化",
    "cross_region_duplicate": "跨区域重复线索未经主办区域裁决，或非主办副本",
    "rule_self_proof": "规则自证：结论由被评估规则自身产出，不能作为该规则的监督信号",
    "insufficient_evidence": "证据暂缺，“未立案/未查实”不能等同于阴性",
    "evidence_not_sufficient": "签发时未确认证据充分",
    "settling_window": "标签仍在冷静期内，尚未稳定",
    "outside_cutoff": "标签稳定时间晚于快照水位",
    "revoked_label": "标签已被撤销",
    "no_label": "尚无生效的签发标签",
    "permission_denied": "签发人权限或辖区不符",
    "duplicate_cross_split": "同一主体已进入更早的时间分区，防止跨分区泄漏",
}

# excluded 标签（由结论映射而来）或“已结案但无标签”结论到排除码
_EXCLUDED_OUTCOME_CODES = {
    "insufficient_evidence": "insufficient_evidence",
    "rule_self_proof": "rule_self_proof",
    "duplicate_pending": "cross_region_duplicate",
}


@dataclass(frozen=True)
class Decision:
    lead_id: str
    included: bool
    exclusion_code: str | None
    detail: str


def evaluate_lead(lead: dict, current_label: dict | None, *, cutoff: str,
                  min_settled_days: int) -> Decision:
    """对单条线索做稳定标签资格判定（跨区域/跨分区分组在快照阶段处理）。"""
    lead_id = lead["lead_id"]

    def reject(code: str, detail: str) -> Decision:
        return Decision(lead_id, False, code, detail)

    if is_open(lead):
        return reject("open_case", f"核查阶段 {lead['stage']}，尚未结案")

    conclusion = lead.get("conclusion")
    outcome = conclusion["outcome"] if conclusion else None

    if current_label is None:
        # 已结案但无生效标签：证据暂缺/跨区域待裁决等结论按策略不签发，
        # 由结论直接给出排除码，而不是落入“无标签”的笼统类别
        code = _EXCLUDED_OUTCOME_CODES.get(outcome, "no_label")
        if code != "no_label":
            return reject(code, f"结论 {outcome} 不签发稳定标签，按治理策略排除")
        return reject("no_label", "不存在 status=issued 的标签版本")
    if current_label["status"] == "revoked":
        return reject("revoked_label", "当前标签版本已撤销")

    if current_label["label"] == "excluded":
        code = _EXCLUDED_OUTCOME_CODES.get(outcome, "insufficient_evidence")
        return reject(code, f"结论 {outcome} 不构成正负样本")

    settled_at = current_label["issued_at"]
    if settled_at > cutoff:
        return reject("outside_cutoff", f"标签签发于 {settled_at}，晚于水位 {cutoff}")
    if add_days(settled_at, min_settled_days) > add_days(cutoff, 0):
        return reject(
            "settling_window",
            f"签发于 {settled_at}，需经过 {min_settled_days} 天冷静期方可稳定",
        )
    if not current_label["basis"]["evidence_sufficient"]:
        return reject("evidence_not_sufficient", "签发记录未确认证据充分")
    if not current_label["basis"]["evidence_ids"]:
        return reject("evidence_not_sufficient", "缺少证据材料登记号")

    return Decision(lead_id, True, None, f"{current_label['label']} 标签已于 {settled_at} 稳定")
