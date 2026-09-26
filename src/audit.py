"""审计追溯：从监控指标下钻到线索、签发版本与证据依据。"""

from __future__ import annotations

from .labels import LabelLedger


def trace_leads(lead_ids: list[str], leads: list[dict], ledger: LabelLedger,
                reviewers: dict[str, dict]) -> list[dict]:
    """为一批 lead_id 构造完整审计链：线索触发 → 标签版本 → 证据 → 签发人。"""
    leads_by_id = {lead["lead_id"]: lead for lead in leads}
    chain = []
    for lead_id in sorted(lead_ids):
        lead = leads_by_id.get(lead_id)
        if lead is None:
            raise KeyError(f"线索 {lead_id} 不存在，指标无法回溯到来源记录")
        versions = []
        for rec in ledger.for_lead(lead_id):
            issuer = reviewers.get(rec["issued_by"])
            versions.append({
                "version": rec["version"],
                "status": rec["status"],
                "label": rec["label"],
                "outcome": rec["basis"]["outcome"],
                "source": rec["basis"]["source"],
                "evidence_ids": list(rec["basis"]["evidence_ids"]),
                "evidence_sufficient": rec["basis"]["evidence_sufficient"],
                "issued_by": rec["issued_by"],
                "issuer_display_name": issuer["display_name"] if issuer else None,
                "issued_at": rec["issued_at"],
                "supersedes_version": rec["supersedes_version"],
                "appeal_id": rec["basis"].get("appeal_id"),
                "case_ref": rec["basis"].get("case_ref"),
            })
        chain.append({
            "lead_id": lead_id,
            "trigger": {
                "kind": lead["trigger"]["kind"],
                "version": lead["trigger"]["version"],
                "rule_ids": list(lead["trigger"]["rule_ids"]),
            },
            "input_watermark_as_of": lead["input_watermark"]["as_of"],
            "dispatch_scope": lead["dispatch"]["scope"],
            "stage": lead["stage"],
            "versions": versions,
        })
    return chain
