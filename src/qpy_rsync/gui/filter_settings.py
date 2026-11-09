from __future__ import annotations

import json

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


def encode_filters(rules: list[FilterRule]) -> str:
    return json.dumps(
        [
            {
                "rule": item.rule,
                "enabled": item.enabled,
                "rule_type": item.rule_type.value,
                "comment": item.comment,
            }
            for item in rules
        ],
        ensure_ascii=False,
    )


def decode_filters(payload: str) -> list[FilterRule]:
    if not payload:
        return []
    raw = json.loads(payload)
    if not isinstance(raw, list):
        raise ValueError("Stored filters must be a list.")
    rules: list[FilterRule] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Stored filter entries must be objects.")
        rules.append(
            FilterRule(
                rule=str(item["rule"]),
                enabled=bool(item.get("enabled", True)),
                rule_type=FilterRuleType(item.get("rule_type", "advanced")),
                comment=str(item.get("comment", "")),
            )
        )
    return rules
