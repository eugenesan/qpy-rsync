from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

from .changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    HiddenItems,
    ObjectKind,
)
from .models import SyncProfile


def _is_hidden(path: str, hidden_paths: set[str]) -> bool:
    """Return whether a path is hidden, directly or by a parent directory."""
    current = path.rstrip("/")
    while current:
        if current in hidden_paths:
            return True
        current = current.rpartition("/")[0]
    return False


@dataclass(slots=True, frozen=True)
class PlanItem:
    path: str
    action: ChangeAction
    comparison_action: ChangeAction
    kind: ObjectKind
    included: bool
    destructive: bool
    size: int | None = None

    @property
    def identity(self) -> tuple[str, ChangeAction, ObjectKind]:
        return (self.path, self.comparison_action, self.kind)


@dataclass(slots=True, frozen=True)
class PlanSummary:
    included: int
    excluded: int
    modified: int
    retained_destination_only: int
    destructive: int
    creates: int
    updates: int
    metadata: int
    replacements: int
    deletions: int
    backup_enabled: bool
    total_size: int = 0


@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    profile_fingerprint: str
    source_operand: str
    destination_operand: str
    items: tuple[PlanItem, ...]
    summary: PlanSummary

    @property
    def included_items(self) -> tuple[PlanItem, ...]:
        return tuple(item for item in self.items if item.included)


def profile_fingerprint(profile: SyncProfile) -> str:
    # Fingerprint synchronization semantics, not profile identity or labels.
    # Ad-hoc profiles are reconstructed by the GUI and therefore receive a new
    # UUID each time; including profile_id would make every plan immediately stale.
    value = profile.to_dict()
    for field in ("profile_id", "name", "description", "schema_version"):
        value.pop(field, None)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def build_execution_plan(
    profile: SyncProfile,
    changes: Iterable[Change],
    decisions: ChangeDecisions,
    hidden: HiddenItems | None = None,
) -> ExecutionPlan:
    changes_list = list(changes)
    items: list[PlanItem] = []
    creates = updates = metadata = replacements = deletions = 0
    included = excluded = retained_destination_only = destructive = 0
    total_size = 0
    modified = decisions.modified_count(changes_list)
    hidden_paths = (
        {path.strip("/") for path in hidden.paths()} if hidden else set()
    )
    for change in changes_list:
        if not decisions.selectable(change):
            continue
        if hidden_paths and _is_hidden(str(change.path), hidden_paths):
            # A hidden item is not part of the sync. The state only lives in
            # memory, so it is gone after the next comparison.
            excluded += 1
            items.append(
                PlanItem(
                    path=change.path.rstrip("/"),
                    action=change.action,
                    comparison_action=change.action,
                    kind=change.kind,
                    included=False,
                    destructive=False,
                    size=change.size,
                )
            )
            continue
        selected = decisions.effective(change) is not ChangeDecision.EXCLUDE
        effective_action = (
            ChangeAction.DELETE
            if change.action is ChangeAction.DESTINATION_ONLY and selected
            else change.action
        )
        is_destructive = selected and effective_action in {ChangeAction.DELETE, ChangeAction.REPLACE}
        item = PlanItem(
            path=change.path.rstrip("/"),
            action=effective_action,
            comparison_action=change.action,
            kind=change.kind,
            included=selected,
            destructive=is_destructive,
            size=change.size,
        )
        items.append(item)
        if selected:
            included += 1
            destructive += int(is_destructive)
            if effective_action in {
                ChangeAction.CREATE,
                ChangeAction.UPDATE_CONTENT,
                ChangeAction.REPLACE,
            }:
                total_size += int(change.size or 0)
            if effective_action is ChangeAction.CREATE:
                creates += 1
            elif effective_action is ChangeAction.UPDATE_CONTENT:
                updates += 1
            elif effective_action is ChangeAction.UPDATE_METADATA:
                metadata += 1
            elif effective_action is ChangeAction.REPLACE:
                replacements += 1
            elif effective_action is ChangeAction.DELETE:
                deletions += 1
        else:
            if change.action is ChangeAction.DESTINATION_ONLY:
                retained_destination_only += 1
            else:
                excluded += 1
    summary = PlanSummary(
        included=included,
        excluded=excluded,
        modified=modified,
        retained_destination_only=retained_destination_only,
        destructive=destructive,
        creates=creates,
        updates=updates,
        metadata=metadata,
        replacements=replacements,
        deletions=deletions,
        backup_enabled=profile.backup.enabled,
        total_size=total_size,
    )
    return ExecutionPlan(
        profile_fingerprint=profile_fingerprint(profile),
        source_operand=profile.source.rsync_operand(),
        destination_operand=profile.destination.rsync_operand(),
        items=tuple(items),
        summary=summary,
    )

@dataclass(slots=True, frozen=True)
class PlanFreshness:
    fresh: bool
    reasons: tuple[str, ...]


def check_plan_freshness(
    plan: ExecutionPlan,
    profile: SyncProfile,
    changes: Iterable[Change],
) -> PlanFreshness:
    reasons: list[str] = []
    if plan.profile_fingerprint != profile_fingerprint(profile):
        reasons.append("profile options changed")
    if plan.source_operand != profile.source.rsync_operand():
        reasons.append("source endpoint changed")
    if plan.destination_operand != profile.destination.rsync_operand():
        reasons.append("destination endpoint changed")
    current = {
        (change.path.rstrip("/"), change.action, change.kind)
        for change in changes
        if ChangeDecisions.selectable(change)
    }
    planned = {item.identity for item in plan.items}
    if current != planned:
        reasons.append("comparison actions changed")
    return PlanFreshness(not reasons, tuple(reasons))
