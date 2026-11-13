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
    # The itemized output of a comparison only carries the metadata of the
    # source. The destination values are known for the objects an inventory
    # listed.
    destination_size: int | None = None
    destination_time: str | None = None

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
        # Most comparisons have no explicit decision at all, and the walk
        # below is repeated for every item. The empty case is common enough
        # to be worth a shortcut.
        if not self._decisions:
            return None
        current = path.rstrip("/")
        while current:
            decision = self._decisions.get(current)
            if decision is not None:
                return decision
            current = current.rpartition("/")[0]
        # The compared folder itself can carry a decision, which covers every
        # item of the comparison.
        return self._decisions.get("")

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


class StashedItems:
    """The items the user stashed from the comparison.

    An item is stashed with the space bar or the context menu and restored
    with the "Show stashed" toggle. A stashed item is not part of the sync;
    the comparison keeps it so it can be restored, and the next comparison
    starts with an empty stash.

    A stashed directory covers everything below it, the same way the
    decisions of a directory cover its children.
    """

    def __init__(self) -> None:
        self._paths: set[str] = set()

    def __bool__(self) -> bool:
        return bool(self._paths)

    def paths(self) -> set[str]:
        """The paths that are stashed."""
        return set(self._paths)

    def count(self) -> int:
        return len(self._paths)

    def add(self, path: str) -> None:
        """Stash a path and everything below it."""
        clean = path.strip("/")
        if clean:
            self._paths.add(clean)

    def restore(self, path: str) -> None:
        """Restore a path and everything below it."""
        clean = path.strip("/")
        if not clean:
            return
        self._paths.discard(clean)
        # A path below a stashed directory stays stashed, so the directory
        # itself has to be restored as well.
        for stashed in list(self._paths):
            if stashed.startswith(clean + "/"):
                self._paths.discard(stashed)

    def toggle(self, path: str) -> bool:
        """Stash a path or restore it.

        Returns the new state: True when the path is stashed.
        """
        clean = path.strip("/")
        if self.is_stashed(clean):
            self.restore(clean)
            return False
        self.add(clean)
        return True

    def is_stashed(self, path: str) -> bool:
        """Return whether a path is stashed, directly or by a parent."""
        clean = path.strip("/")
        if not clean:
            return False
        if clean in self._paths:
            return True
        parent = clean.rpartition("/")[0]
        while parent:
            if parent in self._paths:
                return True
            parent = parent.rpartition("/")[0]
        return False

    def clear(self) -> None:
        """Restore every stashed item."""
        self._paths.clear()

    def reconcile(self, paths: set[str]) -> None:
        """Drop the stashed paths that no longer exist."""
        if not self._paths:
            return
        known = {path.strip("/") for path in paths}
        self._paths = {
            path
            for path in self._paths
            if path in known or any(item.startswith(path + "/") for item in known)
        }
