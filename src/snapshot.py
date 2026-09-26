"""训练用脱敏快照构建：时间切分、稳定标签准入、脱敏变换与排除清单。"""

from __future__ import annotations

import hashlib
from datetime import datetime

from .contracts import validate_contract
from .eligibility import evaluate_lead, Decision
from .labels import LabelLedger
from .timeutil import parse_dt


def pseudonymize(subject_ref: str, salt: str) -> str:
    """不可逆假名化：加盐哈希截断。快照中不保留主体原始标识。"""
    digest = hashlib.sha256(f"{salt}|{subject_ref}".encode("utf-8")).hexdigest()
    return f"subj-{digest[:16]}"


def region_bucket(region_code: str, province_buckets: dict[str, str]) -> str:
    """区县代码下沉到粗粒度大区桶（按省级前缀映射）。"""
    prefix = region_code[:2]
    if prefix not in province_buckets:
        raise KeyError(f"缺少省级前缀 {prefix} 的分桶配置")
    return province_buckets[prefix]


def _month_floor(value: str) -> str:
    dt = parse_dt(value)
    return datetime(dt.year, dt.month, 1, tzinfo=dt.tzinfo).isoformat()


def _assign_split(settled_at: str, split: dict) -> str:
    ts = parse_dt(settled_at)
    if ts < parse_dt(split["train_end"]):
        return "train"
    if ts < parse_dt(split["validation_end"]):
        return "validation"
    return "test"


def build_snapshot(
    *,
    snapshot_id: str,
    created_at: str,
    cutoff: str,
    split: dict,
    min_settled_days: int,
    leads: list[dict],
    ledger: LabelLedger,
    salt: str,
    province_buckets: dict[str, str],
) -> dict:
    """按治理规则构建训练快照。

    依次执行：单条准入判定 → 跨区域重复归并 → 水位/分区校验 →
    同一主体跨分区防泄漏 → 脱敏变换 → 清单汇总与契约校验。
    """
    leads_by_id = {lead["lead_id"]: lead for lead in leads}
    decisions: dict[str, Decision] = {}

    for lead in leads:
        # latest 用于识别“已撤销”，current 只看生效版本
        latest = ledger.latest(lead["lead_id"])
        current = ledger.current(lead["lead_id"])
        if latest is not None and latest["status"] == "revoked":
            decisions[lead["lead_id"]] = Decision(
                lead["lead_id"], False, "revoked_label", "当前标签版本已撤销"
            )
        else:
            decisions[lead["lead_id"]] = evaluate_lead(
                lead, current, cutoff=cutoff, min_settled_days=min_settled_days
            )

    # 跨区域重复归并：同组若多条通过准入，只保留标签稳定最早的一条作为主办记录
    groups: dict[str, list[str]] = {}
    for lead in leads:
        group = lead.get("cross_region_group")
        if group:
            groups.setdefault(group, []).append(lead["lead_id"])

    for group, member_ids in groups.items():
        eligible_members = [mid for mid in member_ids if decisions[mid].included]
        if len(eligible_members) > 1:
            def settled_key(mid):
                return (parse_dt(ledger.current(mid)["issued_at"]), mid)

            keeper = min(eligible_members, key=settled_key)
            for mid in eligible_members:
                if mid != keeper:
                    decisions[mid] = Decision(
                        mid, False, "cross_region_duplicate",
                        f"跨区域组 {group} 已由主办记录 {keeper} 代表，去重排除",
                    )

    # 通过准入者按稳定时间排序后分配时间分区
    accepted = [mid for mid, d in decisions.items() if d.included]
    accepted.sort(key=lambda mid: (parse_dt(ledger.current(mid)["issued_at"]), mid))

    records = []
    seen_subjects: dict[str, str] = {}
    for ordinal, lead_id in enumerate(accepted, start=1):
        lead = leads_by_id[lead_id]
        label = ledger.current(lead_id)
        settled_at = label["issued_at"]
        split_name = _assign_split(settled_at, split)

        if parse_dt(settled_at) > parse_dt(cutoff):
            decisions[lead_id] = Decision(
                lead_id, False, "outside_cutoff", f"标签稳定时间 {settled_at} 晚于水位 {cutoff}"
            )
            continue

        pseudonym = pseudonymize(lead["subject_ref"], salt)
        if pseudonym in seen_subjects and seen_subjects[pseudonym] != split_name:
            earlier_split = seen_subjects[pseudonym]
            decisions[lead_id] = Decision(
                lead_id, False, "duplicate_cross_split",
                f"同一主体已在 {earlier_split} 分区出现，禁止跨分区泄漏",
            )
            continue
        seen_subjects.setdefault(pseudonym, split_name)

        records.append({
            "record_id": f"{snapshot_id}-{ordinal:05d}",
            "lead_id": lead_id,
            "split": split_name,
            "label": label["label"],
            "trigger_version": lead["trigger"]["version"],
            "subject_pseudonym": pseudonym,
            "region_bucket": region_bucket(lead["region_code"], province_buckets),
            "label_settled_at": _month_floor(settled_at),
            "label_version": label["version"],
        })

    excluded = [
        {
            "lead_id": lead_id,
            "exclusion_code": decision.exclusion_code,
            "detail": decision.detail,
        }
        for lead_id, decision in decisions.items()
        if not decision.included
    ]

    split_counts = {"train": 0, "validation": 0, "test": 0}
    for rec in records:
        split_counts[rec["split"]] += 1

    snapshot = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "cutoff": cutoff,
        "split": split,
        "min_label_settled_days": min_settled_days,
        "records": records,
        "excluded": sorted(excluded, key=lambda x: x["lead_id"]),
        "manifest": {
            "lead_count": len(leads),
            "included_count": len(records),
            "excluded_count": len(excluded),
            "positive_count": sum(1 for r in records if r["label"] == "positive"),
            "negative_count": sum(1 for r in records if r["label"] == "negative"),
            "split_counts": split_counts,
            "transformations": [
                f"主体标识使用加盐 SHA-256 假名化（salt 指纹 {hashlib.sha256(salt.encode()).hexdigest()[:8]}）",
                "区域由区县代码下沉为省级大区桶",
                "标签稳定时间按月取整",
                "删除叙述性结论与证据登记号原文，仅保留版本与时间引用",
            ],
        },
    }
    return validate_contract("snapshot", snapshot)
