from __future__ import annotations

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


def filter_arguments(rules: list[FilterRule]) -> list[str]:
    arguments: list[str] = []
    for item in rules:
        if not item.enabled:
            continue
        if item.rule_type is FilterRuleType.INCLUDE:
            arguments.append(f"--include={item.rule}")
        elif item.rule_type is FilterRuleType.EXCLUDE:
            arguments.append(f"--exclude={item.rule}")
        else:
            arguments.extend(("--filter", item.rule))
    return arguments
