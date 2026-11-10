from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChangeAction(StrEnum):
    CREATE = "create"
    UPDATE_CONTENT = "update_content"
    UPDATE_METADATA = "update_metadata"
    DELETE = "delete"
    DESTINATION_ONLY = "destination_only"
    REPLACE = "replace"
    NO_CHANGE = "no_change"
    MESSAGE = "message"


class ObjectKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    DEVICE = "device"
    SPECIAL = "special"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class Change:
    path: str
    action: ChangeAction
    kind: ObjectKind
    itemized_code: str
    size: int | None = None
    modified_time: str | None = None
    link_target: str | None = None
    reason: str = ""

    @property
    def is_deletion(self) -> bool:
        return self.action is ChangeAction.DELETE

    @property
    def is_destination_only(self) -> bool:
        return self.action is ChangeAction.DESTINATION_ONLY


class ChangeDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    INHERIT = "inherit"


@dataclass(slots=True, frozen=True)
class DecisionSummary:
    included: int
    excluded: int
    modified: int
    destructive: int


class ChangeDecisions:
    """Explicit decisions with deterministic parent-directory inheritance."""

    def __init__(self) -> None:
        self._decisions: dict[str, ChangeDecision] = {}
        self._identities: dict[str, tuple[ChangeAction, ObjectKind]] = {}
        # Pre-computed default decision for every path that can appear in the
        # comparison tree. This keeps per-cell painting O(1) instead of scanning
        # the complete change list for every row.
        self._defaults: dict[str, ChangeDecision] = {}

    def explicit(self, path: str) -> ChangeDecision:
        return self._decisions.get(path.rstrip("/"), ChangeDecision.INHERIT)

    def explicit_items(self) -> tuple[tuple[str, ChangeDecision], ...]:
        """Return explicit decisions without exposing the mutable mapping."""
        return tuple(self._decisions.items())

    def set(self, path: str, decision: ChangeDecision) -> None:
        normalized = path.rstrip("/")
        if decision is ChangeDecision.INHERIT:
            self._decisions.pop(normalized, None)
        else:
            self._decisions[normalized] = decision

    def reset(self, path: str) -> None:
        self._decisions.pop(path.rstrip("/"), None)

    def reset_subtree(self, path: str) -> None:
        root = path.rstrip("/")
        stale = [
            item
            for item in self._decisions
            if item == root or item.startswith(root + "/")
        ]
        for item in stale:
            self._decisions.pop(item, None)

    def clear(self) -> None:
        self._decisions.clear()

    def has_explicit(self) -> bool:
        return bool(self._decisions)

    @staticmethod
    def _default_decision_for_path(path: str, changes: list[Change]) -> ChangeDecision:
        normalized = path.rstrip("/")
        change = next(
            (item for item in changes if item.path.rstrip("/") == normalized), None
        )
        if change is not None:
            return (
                ChangeDecision.EXCLUDE
                if change.action is ChangeAction.DESTINATION_ONLY
                else ChangeDecision.INCLUDE
            )
        descendants = [
            item for item in changes if item.path.rstrip("/").startswith(normalized + "/")
        ]
        if descendants and all(
            item.action is ChangeAction.DESTINATION_ONLY for item in descendants
        ):
            return ChangeDecision.EXCLUDE
        return ChangeDecision.INCLUDE

    def is_override_path(self, path: str, changes: list[Change]) -> bool:
        normalized = path.rstrip("/")
        explicit = self.explicit(normalized)
        if explicit is ChangeDecision.INHERIT:
            return False
        default = self._defaults.get(normalized)
        if default is None:
            default = self._default_decision_for_path(normalized, changes)
        return explicit is not default

    def override_paths(self, changes: list[Change]) -> set[str]:
        """Return explicit decisions that differ from their computed default."""
        overrides: set[str] = set()
        for path, explicit in self._decisions.items():
            default = self._defaults.get(path)
            if default is None:
                default = self._default_decision_for_path(path, changes)
            if explicit is not default:
                overrides.add(path)
        return overrides

    def modified_count(self, changes: list[Change]) -> int:
        return len(self.override_paths(changes))

    def effective(self, change: Change) -> ChangeDecision:
        if not self.selectable(change):
            return ChangeDecision.EXCLUDE
        inherited = self.inherited(change.path)
        if inherited is not None:
            return inherited
        if change.action is ChangeAction.DESTINATION_ONLY:
            return ChangeDecision.EXCLUDE
        return ChangeDecision.INCLUDE

    def inherited(self, path: str) -> ChangeDecision | None:
        current = path.rstrip("/")
        while current:
            decision = self._decisions.get(current)
            if decision is not None:
                return decision
            current = current.rpartition("/")[0]
        return None

    def effective_path(self, path: str) -> ChangeDecision:
        return self.inherited(path) or ChangeDecision.INCLUDE

    @staticmethod
    def selectable(change: Change) -> bool:
        return change.action not in {
            ChangeAction.NO_CHANGE,
            ChangeAction.MESSAGE,
        }

    def reconcile(self, changes: list[Change]) -> int:
        current = {change.path.rstrip("/"): (change.action, change.kind) for change in changes}
        current_paths = tuple(current)
        stale = [
            path
            for path in self._decisions
            if (
                path in self._identities
                and current.get(path) != self._identities.get(path)
            )
            or (
                path not in self._identities
                and not any(item.startswith(path + "/") for item in current_paths)
            )
        ]
        for path in stale:
            self._decisions.pop(path, None)
        self._identities = current
        self._defaults = self._build_defaults(current)
        return len(stale)

    @staticmethod
    def _build_defaults(
        current: dict[str, tuple[ChangeAction, ObjectKind]]
    ) -> dict[str, ChangeDecision]:
        defaults: dict[str, ChangeDecision] = {}
        non_destination_paths: set[str] = set()
        for path, (action, _kind) in current.items():
            defaults[path] = (
                ChangeDecision.EXCLUDE
                if action is ChangeAction.DESTINATION_ONLY
                else ChangeDecision.INCLUDE
            )
            if action is not ChangeAction.DESTINATION_ONLY:
                ancestor = path
                while ancestor:
                    non_destination_paths.add(ancestor)
                    ancestor = ancestor.rpartition("/")[0]
        for path in current:
            ancestor = path.rpartition("/")[0]
            while ancestor:
                defaults.setdefault(
                    ancestor,
                    ChangeDecision.INCLUDE
                    if ancestor in non_destination_paths
                    else ChangeDecision.EXCLUDE,
                )
                ancestor = ancestor.rpartition("/")[0]
        return defaults

    def summary(self, changes: list[Change]) -> DecisionSummary:
        included = excluded = destructive = 0
        for change in changes:
            if not self.selectable(change):
                continue
            if self.effective(change) is ChangeDecision.EXCLUDE:
                excluded += 1
            else:
                included += 1
                if change.action is ChangeAction.DELETE:
                    destructive += 1
        return DecisionSummary(
            included, excluded, self.modified_count(changes), destructive
        )
