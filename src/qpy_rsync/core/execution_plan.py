from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import zlib
from typing import Iterable

from qpy_rsync.backend.diagnostics import timed
from qpy_rsync.backend.destination_sizes import (
    build_destination_size_index,
    deleted_size,
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
    # A decision-only delete: the item is still present on the source during
    # Compare, so the sync must hide it there with a sender-side rule.
    synthetic_delete: bool = False

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
    # Order-independent fingerprint of the selectable comparison items, used
    # to skip rebuilding two 500k-element sets in check_plan_freshness().
    comparison_signature: str = ""

    @property
    def included_items(self) -> tuple[PlanItem, ...]:
        return tuple(item for item in self.items if item.included)


def plan_items_fingerprint(items: Iterable[PlanItem]) -> str:
    """Fingerprint plan contents; the filter-text cache keys on this value."""
    digest = sha256()
    for item in items:
        digest.update(item.path.encode("utf-8"))
        digest.update(item.action.value.encode("utf-8"))
        digest.update(item.kind.value.encode("utf-8"))
        digest.update(b"1" if item.included else b"0")
        if item.synthetic_delete:
            digest.update(b"D")
    return digest.hexdigest()


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


def comparison_signature(
    changes: Iterable[Change], extra_paths: frozenset[str] = frozenset()
) -> str:
    """Cheap order-independent fingerprint of the selectable changes."""
    acc = 0
    count = 0
    for change in changes:
        if not ChangeDecisions.selectable(change) and str(change.path).rstrip("/") not in extra_paths:
            continue
        key = (
            f"{str(change.path).rstrip('/')}\0"
            f"{change.action.value}\0{change.kind.value}\0"
        )
        acc ^= zlib.crc32(key.encode("utf-8"))
        count += 1
    return f"{count}:{acc:08x}"


def build_execution_plan(
    profile: SyncProfile,
    changes: Iterable[Change],
    decisions: ChangeDecisions,
    destination_metadata: dict[str, tuple[int | None, str | None]] | None = None,
) -> ExecutionPlan:
    changes_list = list(changes)
    items: list[PlanItem] = []
    creates = updates = metadata_count = deletions = 0
    included = excluded = retained_destination_only = destructive = 0
    total_size = 0
    included_size = 0
    total_deleted = 0
    with timed("plan.destination_index", entries=len(destination_metadata or {})):
        metadata = build_destination_size_index(destination_metadata or {})
    with timed("plan.modified_count", changes=len(changes_list)):
        modified = decisions.modified_count(changes_list)
    has_explicit = decisions.has_explicit()
    kinds: dict[str, ObjectKind] = {}
    delete_paths: set[str] = set()
    delete_sizes: dict[str, int] = {}

    with timed("plan.loop", changes=len(changes_list)):
        for change in changes_list:
            action = change.action
            decision = decisions.effective(change) if has_explicit else None
            delete_decision = decision is ChangeDecision.DELETE
            if action in {ChangeAction.NO_CHANGE, ChangeAction.MESSAGE}:
                if not delete_decision:
                    continue
            clean = str(change.path).rstrip("/")
            if delete_decision:
                selected = True
                effective_action = ChangeAction.DELETE
            else:
                selected = (
                    decision is not ChangeDecision.EXCLUDE
                    if has_explicit
                    else action is not ChangeAction.DESTINATION_ONLY
                )
                effective_action = (
                    ChangeAction.DELETE
                    if action is ChangeAction.DESTINATION_ONLY and selected
                    else action
                )
            is_destructive = selected and effective_action is ChangeAction.DELETE
            item = PlanItem(
                path=clean,
                action=effective_action,
                comparison_action=action,
                kind=change.kind,
                included=selected,
                destructive=is_destructive,
                size=change.size,
                synthetic_delete=delete_decision and action is not ChangeAction.DELETE,
            )
            items.append(item)
            if selected:
                included += 1
                destructive += int(is_destructive)
                size = int(change.size or 0)
                included_size += size
                if effective_action in {
                    ChangeAction.CREATE,
                    ChangeAction.UPDATE_CONTENT,
                }:
                    total_size += size
                if effective_action is ChangeAction.CREATE:
                    creates += 1
                elif effective_action is ChangeAction.UPDATE_CONTENT:
                    updates += 1
                elif effective_action is ChangeAction.UPDATE_METADATA:
                    metadata_count += 1
                elif effective_action is ChangeAction.DELETE:
                    deletions += 1
                    delete_paths.add(clean)
                    kinds[clean] = change.kind
                    # Rsync deletes carry no size of their own. Keep the size
                    # reported for the object so a missing destination listing
                    # does not make the overview show 0 B.
                    delete_sizes[clean] = int(
                        change.destination_size
                        if change.destination_size is not None
                        else (change.size or 0)
                    )
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
            total_deleted += deleted_size(
                path, kinds.get(path, ObjectKind.FILE), metadata,
                delete_sizes, delete_paths,
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
        deletions=deletions,
        deleted_size=total_deleted,
        backup_enabled=profile.backup.enabled,
        total_size=total_size,
        included_size=included_size,
    )
    with timed("plan.digest"):
        signature = decision_signature(decisions)
    with timed("plan.comparison_signature", changes=len(changes_list)):
        comparable = comparison_signature(
            changes_list,
            frozenset(item.path for item in items if item.synthetic_delete),
        )
    return ExecutionPlan(
        items_fingerprint=plan_items_fingerprint(items),
        decision_signature=signature,
        profile_fingerprint=profile_fingerprint(profile),
        source_operand=profile.source.rsync_operand(),
        destination_operand=profile.destination.rsync_operand(),
        items=tuple(items),
        summary=summary,
        comparison_signature=comparable,
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
    changes_list = list(changes)
    if plan.profile_fingerprint != profile_fingerprint(profile):
        reasons.append("profile options changed")
    if plan.source_operand != profile.source.rsync_operand():
        reasons.append("source endpoint changed")
    if plan.destination_operand != profile.destination.rsync_operand():
        reasons.append("destination endpoint changed")
    if decision_signature is not None and plan.decision_signature != decision_signature:
        reasons.append("decisions changed")
    synthetic_paths = frozenset(
        item.path for item in plan.items if item.synthetic_delete
    )
    if plan.comparison_signature and (
        plan.comparison_signature == comparison_signature(changes_list, synthetic_paths)
    ):
        # The comparison is identical; skip the two 500k-element set builds.
        pass
    else:
        existing_paths = {str(change.path).rstrip("/") for change in changes_list}
        current = {
            (change.path.rstrip("/"), change.action, change.kind)
            for change in changes_list
            if ChangeDecisions.selectable(change)
            or str(change.path).rstrip("/") in synthetic_paths
        }
        planned = {
            item.identity for item in plan.items
            if not item.synthetic_delete or item.path in existing_paths
        }
        if current != planned:
            reasons.append("comparison decisions changed")
    return PlanFreshness(not reasons, tuple(reasons))
