"""上线后监控：命中分布与人工负担的前后窗口对比。"""

from __future__ import annotations

from collections import Counter

from .contracts import validate_contract
from .timeutil import parse_dt


def load_deployments(document: dict) -> list[dict]:
    validate_contract("deployment", document)
    return document["deployments"]


def load_metrics(document: dict) -> dict:
    return validate_contract("metrics", document)

def window_stats(hits: list[dict]) -> dict:
    """单窗口聚合：命中量、区域分布、人工负担、最终标签分布。"""
    total = len(hits)
    manual = [h for h in hits if h["needs_manual_review"]]
    minutes = sum(h["review_minutes"] for h in hits)
    labeled = [h for h in hits if h["final_label"] in ("positive", "negative")]
    positives = sum(1 for h in labeled if h["final_label"] == "positive")

    return {
        "hit_count": total,
        "region_distribution": dict(Counter(h["region_code"] for h in hits)),
        "manual_review_rate": round(len(manual) / total, 4) if total else 0.0,
        "total_review_minutes": round(minutes, 2),
        "avg_review_minutes": round(minutes / total, 2) if total else 0.0,
        "labeled_count": len(labeled),
        "positive_rate": round(positives / len(labeled), 4) if labeled else None,
        "lead_ids": sorted(h["lead_id"] for h in hits),
    }


def compare_deployment(metrics_doc: dict, deployment: dict) -> dict:
    """计算上线前后命中分布与人工负担变化，并校验窗口归属与版本一致。"""
    if metrics_doc["deployment_id"] != deployment["deployment_id"]:
        raise ValueError("指标文档与上线记录不匹配")

    launched = parse_dt(deployment["launched_at"])
    pre, post = [], []
    for hit in metrics_doc["lead_hits"]:
        hit_at = parse_dt(hit["hit_at"])
        expected = "pre" if hit_at < launched else "post"
        if hit["window"] != expected:
            raise ValueError(
                f"线索 {hit['lead_id']} 命中时间 {hit['hit_at']} 相对上线时点 "
                f"{deployment['launched_at']} 应属 {expected} 窗口，实际标记为 {hit['window']}"
            )
        (pre if expected == "pre" else post).append(hit)

    pre_stats = window_stats(pre)
    post_stats = window_stats(post)

    def delta(key):
        before, after = pre_stats[key], post_stats[key]
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            return round(after - before, 4)
        return None

    return {
        "deployment_id": deployment["deployment_id"],
        "version": deployment["version"],
        "change_summary": deployment.get("change_summary"),
        "pre": pre_stats,
        "post": post_stats,
        "delta": {
            "hit_count": delta("hit_count"),
            "manual_review_rate": delta("manual_review_rate"),
            "total_review_minutes": delta("total_review_minutes"),
            "avg_review_minutes": delta("avg_review_minutes"),
            "positive_rate": delta("positive_rate")
            if pre_stats["positive_rate"] is not None and post_stats["positive_rate"] is not None
            else None,
        },
    }
