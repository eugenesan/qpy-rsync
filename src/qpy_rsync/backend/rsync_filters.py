from __future__ import annotations
from pathlib import Path
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule

def validate_rule(rule: FilterRule) -> str:
    value = rule.rule.strip()
    if not value:
        return "Pattern or rule is required."
    if any(character in value for character in ("\x00", "\n", "\r")):
        return "Patterns and rules must be a single line without NUL characters."
    if rule.rule_type is FilterRuleType.ADVANCED and not value.startswith(("+ ", "- ", "P ", "R ", "H ", "S ", ". ", ": ", "!", "clear")):
        return "Advanced rules require a recognized rsync filter prefix."
    return ""

def import_filter_file(path: Path) -> list[FilterRule]:
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            rules.append(FilterRule(value, rule_type=FilterRuleType.ADVANCED))
    return rules

def export_filter_file(path: Path, rules: list[FilterRule]) -> None:
    lines = []
    for rule in rules:
        if rule.comment:
            lines.append(f"# {rule.comment}")
        if rule.enabled:
            prefix = "+ " if rule.rule_type is FilterRuleType.INCLUDE else "- " if rule.rule_type is FilterRuleType.EXCLUDE else ""
            lines.append(prefix + rule.rule)
        else:
            lines.append(f"# disabled: {rule.rule_type.value}: {rule.rule}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
