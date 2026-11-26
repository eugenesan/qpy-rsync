from __future__ import annotations

import re
from pathlib import Path

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule

# rsync new-style filter rules: short prefixes, long names and modifiers.
_SHORT_RULES = frozenset("+-.:HSPR!")
_LONG_RULES = frozenset(
    {
        "exclude",
        "include",
        "merge",
        "dir-merge",
        "hide",
        "show",
        "protect",
        "risk",
        "clear",
    }
)
_MODIFIERS = frozenset("/!srpxCne-+")
_TOKEN_RE = re.compile(r"^([^\s_]+)(?:[ \t_]+(.*))?$")


def parse_advanced_rule(value: str) -> tuple[str, str | None] | None:
    """Split an rsync filter rule into its rule token and its pattern.

    Returns ``None`` for anything rsync would not recognise as a rule. A
    ``clear`` rule has no pattern; every other rule must have one.
    """
    text = value.strip()
    match = _TOKEN_RE.match(text)
    if match is None:
        return None
    token, pattern = match.group(1), match.group(2)

    if "," in token:
        name, modifiers = token.split(",", 1)
        if not modifiers or any(char not in _MODIFIERS for char in modifiers):
            return None
    else:
        name, modifiers = token, ""
        if name in _LONG_RULES:
            pass
        elif name and name[0] in _SHORT_RULES:
            modifiers = name[1:]
            if any(char not in _MODIFIERS for char in modifiers):
                return None
            name = name[0]
        else:
            return None

    if name not in _LONG_RULES and name not in _SHORT_RULES:
        return None
    is_clear = name == "clear" or name == "!"
    if is_clear:
        return (token, None) if pattern is None else None
    if pattern is None or not pattern:
        return None
    return token, pattern


def is_advanced_rule(value: str) -> bool:
    """Whether a line is an rsync filter rule rather than a bare pattern."""
    return parse_advanced_rule(value) is not None


def shorten_filter_rule(rule: str, prefix: str) -> str:
    """Remove a leading directory from a rule that names a path inside it.

    Used when a comparison folder becomes the new transfer root: a rule like
    ``- /docs/private/`` becomes ``- /private/`` when diving into ``docs``.
    Rules outside the prefix, comments and empty lines are left alone. A rule
    naming exactly the eliminated folder becomes a match for the new root
    itself, and an unnamed pattern naming it is dropped (it can no longer
    select anything below the new root).
    """
    clean = prefix.strip().strip("/")
    if not clean:
        return rule
    line = rule.strip()
    if not line or line.startswith("#"):
        return rule
    parsed = parse_advanced_rule(line)
    token = parsed[0] if parsed is not None else ""
    pattern = (parsed[1] if parsed is not None else line) or ""
    if not pattern:
        return rule

    rooted = pattern.startswith("/")
    value = pattern.lstrip("/")
    if value != clean and not value.startswith(clean + "/"):
        return rule
    value = value[len(clean):].lstrip("/")
    if not value:
        return f"{token} /" if token else ""
    result = ("/" if rooted else "") + value
    return f"{token} {result}" if token else result


def shorten_filter_text(text: str, prefix: str) -> str:
    """Apply :func:`shorten_filter_rule` to every line of a filter file."""
    out: list[str] = []
    for line in text.splitlines():
        shortened = shorten_filter_rule(line, prefix)
        if shortened:
            out.append(shortened)
    return "\n".join(out)


def validate_rule(rule: FilterRule) -> str:
    value = rule.rule.strip()
    if not value:
        return "Pattern or rule is required."
    if any(character in value for character in ("\x00", "\n", "\r")):
        return "Patterns and rules must be a single line without NUL characters."
    if rule.rule_type is FilterRuleType.ADVANCED:
        if parse_advanced_rule(value) is None:
            return "Not a recognized rsync filter rule."
    return ""


def import_filter_file(path: Path) -> list[FilterRule]:
    rules: list[FilterRule] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            rules.append(FilterRule(value, rule_type=FilterRuleType.ADVANCED))
    return rules


def export_filter_file(path: Path, rules: list[FilterRule]) -> None:
    lines: list[str] = []
    for rule in rules:
        if rule.comment:
            lines.append(f"# {rule.comment}")
        if rule.enabled:
            prefix = (
                "+ "
                if rule.rule_type is FilterRuleType.INCLUDE
                else "- "
                if rule.rule_type is FilterRuleType.EXCLUDE
                else ""
            )
            lines.append(prefix + rule.rule)
        else:
            lines.append(f"# disabled: {rule.rule_type.value}: {rule.rule}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def filter_text_to_rules(text: str) -> list[FilterRule]:
    """Build the active rsync rules from the text editor's source of truth."""
    rules: list[FilterRule] = []
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if is_advanced_rule(value):
            rule = value
        else:
            rule = f"- {value}"
        rules.append(FilterRule(rule, rule_type=FilterRuleType.ADVANCED))
    return rules


def rules_to_filter_text(rules: list[FilterRule]) -> str:
    """Render older structured rules as editable filter text."""
    lines: list[str] = []
    for item in rules:
        if item.rule_type is FilterRuleType.INCLUDE:
            base = (
                item.rule
                if item.rule.lstrip().startswith("+")
                else f"+ {item.rule}"
            )
        elif item.rule_type is FilterRuleType.EXCLUDE:
            base = item.rule
        else:
            base = item.rule
        if item.comment:
            lines.append(f"# {item.comment}")
        if not item.enabled:
            base = f"# {base}"
        lines.append(base)
    return "\n".join(lines)
