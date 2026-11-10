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

    def explicit(self, path: str) -> ChangeDecision:
        return self._decisions.get(path.rstrip("/"), ChangeDecision.INHERIT)

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
        return explicit is not self._default_decision_for_path(normalized, changes)

    def modified_count(self, changes: list[Change]) -> int:
        count = 0
        for path in self._decisions:
            if self.is_override_path(path, changes):
                count += 1
        return count

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
        return len(stale)

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
