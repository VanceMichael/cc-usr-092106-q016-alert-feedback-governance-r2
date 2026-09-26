"""复核者权限：只有在职的高级复核者能在辖区内签发标签。"""

from __future__ import annotations

from .contracts import validate_contract


class PermissionError_(Exception):
    """签发权限不足。"""


def load_reviewers(document: dict) -> dict[str, dict]:
    validate_contract("reviewer", document)
    return {r["reviewer_id"]: r for r in document["reviewers"]}


def can_issue(reviewer: dict, region_code: str) -> bool:
    return (
        reviewer.get("active") is True
        and "senior_reviewer" in reviewer["roles"]
        and ("*" in reviewer["region_scopes"] or region_code in reviewer["region_scopes"])
    )


def assert_can_issue(reviewers: dict[str, dict], reviewer_id: str, region_code: str) -> dict:
    reviewer = reviewers.get(reviewer_id)
    if reviewer is None:
        raise PermissionError_(f"复核者 {reviewer_id} 不存在")
    if not reviewer.get("active"):
        raise PermissionError_(f"复核者 {reviewer_id} 已停用，无权签发")
    if "senior_reviewer" not in reviewer["roles"]:
        raise PermissionError_(f"{reviewer_id} 不具备 senior_reviewer 角色，调查结论不能自行升级为稳定标签")
    if not ("*" in reviewer["region_scopes"] or region_code in reviewer["region_scopes"]):
        raise PermissionError_(f"{reviewer_id} 的承办区域不含 {region_code}，不得跨辖区签发")
    return reviewer
