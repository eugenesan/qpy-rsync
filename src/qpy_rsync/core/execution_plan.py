from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

from qpy_rsync.backend.destination_sizes import (
    build_destination_size_index,
    destination_subtree_size,
)

from .changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    StashedItems,
    ObjectKind,
)
from .models import SyncProfile


def _is_stashed(path: str, stashed_paths: set[str]) -> bool:
    """Return whether a path is stashed, directly or by a parent directory."""
    current = path.rstrip("/")
    while current:
        if current in stashed_paths:
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
    deleted_size: int = 0
    backup_enabled: bool = False
    total_size: int = 0
    # The size of every included item, whether or not its content is
    # transferred. This is the number the overview shows as "Selected".
    included_size: int = 0


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
    stashed: StashedItems | None = None,
    destination_metadata: dict[str, tuple[int | None, str | None]] | None = None,
) -> ExecutionPlan:
    changes_list = list(changes)
    items: list[PlanItem] = []
    creates = updates = metadata_count = replacements = deletions = 0
    included = excluded = retained_destination_only = destructive = 0
    total_size = 0
    included_size = 0
    deleted_size = 0
    metadata = build_destination_size_index(destination_metadata or {})
    modified = decisions.modified_count(changes_list)
    stashed_paths = (
        {path.strip("/") for path in stashed.paths()} if stashed else set()
    )
    for change in changes_list:
        if not decisions.selectable(change):
            continue
        if stashed_paths and _is_stashed(str(change.path), stashed_paths):
            # A stashed item is not part of the sync. The state only lives in
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
            included_size += int(change.size or 0)
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
                metadata_count += 1
            elif effective_action is ChangeAction.REPLACE:
                replacements += 1
            elif effective_action is ChangeAction.DELETE:
                deletions += 1
        else:
            if change.action is ChangeAction.DESTINATION_ONLY:
                retained_destination_only += 1
            else:
                excluded += 1

    # The deleted size is the size of the selected deletions only. A deleted
    # directory contributes the sizes of the selected items below it, and its
    # children are not counted again when they are part of the same plan.
    kinds = {str(change.path).rstrip("/"): change.kind for change in changes_list}
    delete_paths = {
        item.path for item in items if item.included and item.action is ChangeAction.DELETE
    }
    for path in delete_paths:
        if any(
            path.startswith(parent + "/")
            for parent in delete_paths
            if parent != path
        ):
            continue
        # A directory's subtree size already includes its selected children;
        # those children are skipped by the covered check above.
        deleted_size += destination_subtree_size(
            path, kinds.get(path, ObjectKind.FILE), metadata
        )

    summary = PlanSummary(
        included=included,
        excluded=excluded,
        modified=modified,
        retained_destination_only=retained_destination_only,
        destructive=destructive,
        creates=creates,
        updates=updates,
        metadata=metadata_count,
        replacements=replacements,
        deletions=deletions,
        deleted_size=deleted_size,
        backup_enabled=profile.backup.enabled,
        total_size=total_size,
        included_size=included_size,
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
