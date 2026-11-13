"""Matching rsync filter patterns against comparison paths.

The filters of the application are rsync rules. The user interface offers
them the way FreeFileSync does: a menu entry that filters the selected item
by extension, by name or by its relative path. The rules that this produces
are ordinary rsync patterns, so they can also be edited by hand and are
passed to rsync unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


@dataclass(frozen=True, slots=True)
class FilterPhrase:
    """A rsync pattern that a user can pick for the selected item."""

    label: str
    pattern: str
    rule_type: FilterRuleType = FilterRuleType.EXCLUDE

    def to_rule(self, comment: str = "") -> FilterRule:
        return FilterRule(
            self.pattern,
            rule_type=self.rule_type,
            comment=comment,
        )


def extension_of(path: str) -> str:
    """Return the extension of a path without the dot."""
    name = path.rstrip("/").rpartition("/")[2]
    if "." not in name:
        return ""
    return name.rpartition(".")[2]


def phrases_for(path: str, *, is_directory: bool) -> list[FilterPhrase]:
    """The three ways FreeFileSync offers to filter the selected item.

    The patterns are rsync patterns, so they mean the same thing to the
    application and to rsync itself.
    """
    clean = path.strip("/")
    name = clean.rpartition("/")[2]
    phrases: list[FilterPhrase] = []

    extension = extension_of(clean)
    if extension:
        phrases.append(
            FilterPhrase(
                label=f"*.{extension}",
                pattern=f"*.{extension}",
            )
        )

    # The name of the item at any depth.
    if name:
        suffix = "/" if is_directory else ""
        phrases.append(
            FilterPhrase(
                label=f"*/{name}{suffix}",
                pattern=f"*/{name}{suffix}",
            )
        )

    # The item at its exact place in the tree.
    if clean:
        suffix = "/" if is_directory else ""
        phrases.append(
            FilterPhrase(
                label=f"/{clean}{suffix}",
                pattern=f"/{clean}{suffix}",
            )
        )
    return phrases


def matches(pattern: str, path: str) -> bool:
    """Return whether an rsync pattern matches a comparison path.

    Only the subset of rsync patterns that the application offers is
    understood: a leading or trailing slash anchors the pattern to the root
    of the comparison, and a star matches any number of characters. The
    patterns the menu produces are matched by this function too, so a rule
    added from the menu hides the same rows that rsync would skip.
    """
    if not pattern:
        return False
    clean = path.strip("/")
    anchored = pattern.startswith("/")
    body = pattern[1:] if anchored else pattern
    # A trailing slash marks a directory pattern, which covers everything
    # below it.
    trailing = body.endswith("/")
    if trailing:
        body = body.rstrip("/")
    body = body.strip("/")
    if not body:
        return False

    pattern_parts = body.split("/")
    path_parts = clean.split("/")

    if anchored:
        # The pattern is matched against the start of the path.
        if trailing:
            return _match_segments(pattern_parts, path_parts[: len(pattern_parts)])
        return _match_segments(pattern_parts, path_parts)

    # An unanchored pattern matches at any depth.
    for start in range(len(path_parts)):
        rest = path_parts[start:]
        if trailing:
            if _match_segments(pattern_parts, rest[: len(pattern_parts)]):
                return True
        elif _match_segments(pattern_parts, rest):
            return True
    return False


def _match_segments(pattern_parts: list[str], path_parts: list[str]) -> bool:
    """Match the parts of a pattern against the parts of a path."""
    if not pattern_parts:
        return not path_parts
    head = pattern_parts[0]
    if head == "**":
        # Match any number of parts.
        for index in range(len(path_parts) + 1):
            if _match_segments(pattern_parts[1:], path_parts[index:]):
                return True
        return False
    if not path_parts:
        return False
    if not _match_part(head, path_parts[0]):
        return False
    return _match_segments(pattern_parts[1:], path_parts[1:])


def _match_part(pattern: str, value: str) -> bool:
    """Match a single path part against a pattern part."""
    if "*" not in pattern and "?" not in pattern and "[" not in pattern:
        return pattern == value
    return _wildcard(pattern, value)


def _wildcard(pattern: str, value: str) -> bool:
    """Match a shell style pattern against a value."""
    from fnmatch import fnmatchcase

    return fnmatchcase(value, pattern)
