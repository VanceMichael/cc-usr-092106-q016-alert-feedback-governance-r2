"""极简 JSON Schema 校验器。

仅支持本仓库 contracts/ 下契约用到的关键字，避免引入第三方依赖：
type / required / properties / items / enum / const / minimum / minLength /
minItems / pattern / additionalProperties，以及 date-time 格式与类型并集。
"""

from __future__ import annotations

import re
from datetime import datetime

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, bool) is False and isinstance(v, int),
    "number": lambda v: isinstance(v, bool) is False and isinstance(v, (int, float)),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(ValueError):
    """文档不符合契约。"""


def _check_type(value, expected, path):
    types = expected if isinstance(expected, list) else [expected]
    for t in types:
        if _TYPE_CHECKS[t](value):
            return
    raise SchemaError(f"{path or '#'} 类型应为 {types}，实际为 {type(value).__name__}")


def validate(instance, schema, path: str = "") -> None:
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{path or '#'} 必须等于 {schema['const']!r}")

    if "type" in schema:
        _check_type(instance, schema["type"], path)

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path or '#'} 取值 {instance!r} 不在允许范围内")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise SchemaError(f"{path or '#'} 长度不足 {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            raise SchemaError(f"{path or '#'} 不匹配模式 {schema['pattern']}")
        if schema.get("format") == "date-time" and not _parse_datetime(instance):
            raise SchemaError(f"{path or '#'} 不是合法的 date-time：{instance}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaError(f"{path or '#'} 小于最小值 {schema['minimum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaError(f"{path or '#'} 至少需要 {schema['minItems']} 个元素")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                validate(item, item_schema, f"{path}[{i}]")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaError(f"{path or '#'} 缺少必要字段 {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise SchemaError(f"{path or '#'} 存在未声明字段 {sorted(extra)}")
        for key, subschema in properties.items():
            if key in instance:
                validate(instance[key], subschema, f"{path}.{key}" if path else f".{key}")


def _parse_datetime(text: str):
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    # 治理记录的时间必须显式带时区，避免跨区域比较时出现歧义
    return dt if dt.tzinfo is not None else None
