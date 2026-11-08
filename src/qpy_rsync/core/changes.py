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

    def effective(self, change: Change) -> ChangeDecision:
        if not self.selectable(change):
            return ChangeDecision.EXCLUDE
        return self.effective_path(change.path)

    def effective_path(self, path: str) -> ChangeDecision:
        current = path.rstrip("/")
        while current:
            decision = self._decisions.get(current)
            if decision is not None:
                return decision
            current = current.rpartition("/")[0]
        return ChangeDecision.INCLUDE

    @staticmethod
    def selectable(change: Change) -> bool:
        return change.action not in {ChangeAction.NO_CHANGE, ChangeAction.MESSAGE}

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
        return DecisionSummary(included, excluded, destructive)
