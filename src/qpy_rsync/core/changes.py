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
        # Paths whose decision was dropped because it no longer applies to
        # the item still shown in the comparison, with the reason.
        self._conflicts: dict[str, str] = {}

    def conflicts(self) -> dict[str, str]:
        """The decisions that need review after the last reconciliation."""
        return dict(self._conflicts)

    def conflicted(self, path: str) -> bool:
        return path.rstrip("/") in self._conflicts

    def resolve_conflict(self, path: str) -> None:
        """A fresh decision was made; the conflict is no longer open."""
        self._conflicts.pop(path.rstrip("/"), None)

    def accept_defaults_for_conflicts(self) -> int:
        """Give up the decisions that no longer apply, clearing their flags."""
        paths = tuple(self._conflicts)
        for path in paths:
            self._decisions.pop(path, None)
        self._conflicts.clear()
        return len(paths)

    def explicit(self, path: str) -> ChangeDecision:
        return self._decisions.get(path.rstrip("/"), ChangeDecision.INHERIT)

    def explicit_items(self) -> tuple[tuple[str, ChangeDecision], ...]:
        """Return explicit decisions without exposing the mutable mapping."""
        return tuple(self._decisions.items())

    def set(self, path: str, decision: ChangeDecision) -> None:
        normalized = path.rstrip("/")
        self._conflicts.pop(normalized, None)
        if decision is ChangeDecision.INHERIT:
            self._decisions.pop(normalized, None)
        else:
            self._decisions[normalized] = decision

    def reset(self, path: str) -> None:
        clean = path.rstrip("/")
        self._decisions.pop(clean, None)
        self._conflicts.pop(clean, None)

    def reset_subtree(self, path: str) -> None:
        root = path.rstrip("/")
        stale = [
            item
            for item in self._decisions
            if item == root or item.startswith(root + "/")
        ]
        for item in stale:
            self._decisions.pop(item, None)
        for item in tuple(self._conflicts):
            if item == root or item.startswith(root + "/"):
                self._conflicts.pop(item, None)

    def clear(self) -> None:
        self._decisions.clear()
        self._conflicts.clear()

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

    def reconcile(
        self,
        changes: list[Change],
        *,
        preserve: bool = False,
        detect_inherited: bool = False,
    ) -> int:
        """Drop decisions that no longer describe the comparison.

        An EXCLUDE is preserved by path: it can only narrow the sync. An
        INCLUDE is preserved only while the item stays non-destructive — if
        it became destination-only, the old decision would silently turn into
        a DELETE, so it is dropped and flagged for review. Decisions on paths
        that vanished are dropped without a flag; they are not on the list.
        With ``preserve`` off, the user asked for a fresh comparison, so
        stale decisions are dropped silently — no conflict is reported for
        work they deliberately discarded. ``detect_inherited`` is an opt-in
        extra check for INCLUDE decisions on folders: it flags them when a
        destination-only item appeared below them that was not there when the
        decision was made. It is off by default because a folder-wide INCLUDE
        is often a deliberate choice to own everything below that folder.
        """
        current = {change.path.rstrip("/"): (change.action, change.kind) for change in changes}
        current_paths = tuple(current)
        self._conflicts.clear()
        stale: list[str] = []
        for path, decision in self._decisions.items():
            exists = path in current
            has_descendants = any(
                item.startswith(path + "/") for item in current_paths
            )
            identity_changed = (
                path in self._identities
                and current.get(path) != self._identities.get(path)
            )
            if not exists and not has_descendants:
                # Nothing to apply the decision to: not shown in the list.
                stale.append(path)
                continue
            if not preserve:
                # A fresh comparison discards every stale decision silently.
                if identity_changed:
                    stale.append(path)
                continue
            if not identity_changed:
                # The decision still says exactly what it did before.
                continue
            if decision is ChangeDecision.EXCLUDE:
                # Excluding only narrows the sync; it cannot authorize a
                # write to an item the user never reviewed.
                continue
            new_action = current[path][0] if exists else None
            if new_action is ChangeAction.DESTINATION_ONLY:
                # Including this would turn the item into a DELETE. A prior
                # decision on a different action must not silently do that.
                stale.append(path)
                self._conflicts[path] = (
                    "The item is now destination-only; including it would "
                    "delete it."
                )
        if detect_inherited and preserve and self._identities:
            # A folder-level INCLUDE can silently authorize a DELETE for a
            # destination-only item that appeared below it after the decision.
            # Compare the current and previous sets of destination-only paths
            # covered by each explicit INCLUDE.
            for path, decision in self._decisions.items():
                if path in stale or decision is not ChangeDecision.INCLUDE:
                    continue
                prefix = path + "/" if path else ""
                covered = {
                    item
                    for item, (action, _kind) in current.items()
                    if action is ChangeAction.DESTINATION_ONLY
                    and (item == path or item.startswith(prefix))
                }
                if not covered:
                    continue
                previous = {
                    item
                    for item, (action, _kind) in self._identities.items()
                    if action is ChangeAction.DESTINATION_ONLY
                    and (item == path or item.startswith(prefix))
                }
                appeared = covered - previous
                if appeared:
                    stale.append(path)
                    self._conflicts[path] = (
                        f"{len(appeared)} destination-only item(s) appeared "
                        "below this included folder."
                    )
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

    def replace(self, decisions: dict[str, ChangeDecision]) -> None:
        """Restore a complete set of explicit decisions."""
        self._decisions = dict(decisions)


class DecisionHistory:
    """A bounded undo/redo stack of decision snapshots."""

    def __init__(self, limit: int = 100) -> None:
        self._undo: list[dict[str, ChangeDecision]] = []
        self._redo: list[dict[str, ChangeDecision]] = []
        self._limit = limit

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def record(self, before: dict[str, ChangeDecision], after: dict[str, ChangeDecision]) -> None:
        if before == after:
            return
        self._undo.append(dict(before))
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: dict[str, ChangeDecision]) -> dict[str, ChangeDecision] | None:
        if not self._undo:
            return None
        previous = self._undo.pop()
        self._redo.append(dict(current))
        return previous

    def redo(self, current: dict[str, ChangeDecision]) -> dict[str, ChangeDecision] | None:
        if not self._redo:
            return None
        following = self._redo.pop()
        self._undo.append(dict(current))
        return following

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
