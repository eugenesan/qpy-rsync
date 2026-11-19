from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

from qpy_rsync.backend.diagnostics import timed
from qpy_rsync.backend.destination_sizes import (
    build_destination_size_index,
    destination_subtree_size,
)

from .changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    ObjectKind,
)
from .models import SyncProfile


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
    decision_signature: str = ""
    # A cheap content fingerprint used to reuse generated rsync filter rules
    # when a rebuilt plan has exactly the same items and decisions.
    items_fingerprint: str = ""

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


def decision_signature(decisions) -> str:
    """Fingerprint the decisions that affect the execution plan."""
    return sha256(
        json.dumps(
            sorted(decisions.explicit_items()),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def build_execution_plan(
    profile: SyncProfile,
    changes: Iterable[Change],
    decisions: ChangeDecisions,
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
    has_explicit = decisions.has_explicit()
    kinds: dict[str, ObjectKind] = {}
    delete_paths: set[str] = set()

    with timed("plan.loop", changes=len(changes_list)):
        for change in changes_list:
            action = change.action
            if action in {ChangeAction.NO_CHANGE, ChangeAction.MESSAGE}:
                continue
            clean = str(change.path).rstrip("/")
            selected = (
                decisions.effective(change) is not ChangeDecision.EXCLUDE
                if has_explicit
                else action is not ChangeAction.DESTINATION_ONLY
            )
            effective_action = (
                ChangeAction.DELETE
                if action is ChangeAction.DESTINATION_ONLY and selected
                else action
            )
            is_destructive = selected and effective_action in {
                ChangeAction.DELETE,
                ChangeAction.REPLACE,
            }
            items.append(
                PlanItem(
                    path=clean,
                    action=effective_action,
                    comparison_action=action,
                    kind=change.kind,
                    included=selected,
                    destructive=is_destructive,
                    size=change.size,
                )
            )
            if selected:
                included += 1
                destructive += int(is_destructive)
                size = int(change.size or 0)
                included_size += size
                if effective_action in {
                    ChangeAction.CREATE,
                    ChangeAction.UPDATE_CONTENT,
                    ChangeAction.REPLACE,
                }:
                    total_size += size
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
                    delete_paths.add(clean)
                    kinds[clean] = change.kind
            elif action is ChangeAction.DESTINATION_ONLY:
                retained_destination_only += 1
            else:
                excluded += 1

    # The deleted size is the size of the selected deletions only. A deleted
    # directory contributes the sizes of the selected items below it, and its
    # children are not counted again when they are part of the same plan.
    def has_delete_ancestor(path: str) -> bool:
        parent = path.rpartition("/")[0]
        while parent:
            if parent in delete_paths:
                return True
            parent = parent.rpartition("/")[0]
        return False

    with timed("plan.deleted_sizes", paths=len(delete_paths)):
        for path in delete_paths:
            if has_delete_ancestor(path):
                continue
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
    signature = decision_signature(decisions)
    digest = sha256()
    for item in items:
        digest.update(item.path.encode("utf-8"))
        digest.update(item.action.value.encode("utf-8"))
        digest.update(item.kind.value.encode("utf-8"))
        digest.update(b"1" if item.included else b"0")
    return ExecutionPlan(
        items_fingerprint=digest.hexdigest(),
        decision_signature=signature,
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
    decision_signature: str | None = None,
) -> PlanFreshness:
    reasons: list[str] = []
    if plan.profile_fingerprint != profile_fingerprint(profile):
        reasons.append("profile options changed")
    if plan.source_operand != profile.source.rsync_operand():
        reasons.append("source endpoint changed")
    if plan.destination_operand != profile.destination.rsync_operand():
        reasons.append("destination endpoint changed")
    if decision_signature is not None and plan.decision_signature != decision_signature:
        reasons.append("decisions changed")
    current = {
        (change.path.rstrip("/"), change.action, change.kind)
        for change in changes
        if ChangeDecisions.selectable(change)
    }
    planned = {item.identity for item in plan.items}
    if current != planned:
        reasons.append("comparison actions changed")
    return PlanFreshness(not reasons, tuple(reasons))
