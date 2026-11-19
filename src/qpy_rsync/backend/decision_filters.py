from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
from typing import Iterator

from qpy_rsync.core.changes import ChangeAction, ObjectKind
from qpy_rsync.core.execution_plan import ExecutionPlan, PlanItem


def _pattern(item: PlanItem) -> str:
    path = item.path.strip("/")
    suffix = "/***" if item.kind is ObjectKind.DIRECTORY else ""
    return f"/{path}{suffix}"


def decision_filter_lines(plan: ExecutionPlan) -> list[str]:
    lines: list[str] = []
    excluded_directories = {
        item.path.strip("/")
        for item in plan.items
        if not item.included and item.kind is ObjectKind.DIRECTORY
    }
    # An included item that lives below an excluded directory needs an
    # explicit include, otherwise the exclude would hide it. A set of the
    # excluded directories makes the check linear in the number of items.
    included_overrides: list[PlanItem] = []
    for item in plan.items:
        if not item.included:
            continue
        clean = item.path.strip("/")
        # Walk the path components: an excluded ancestor makes this item an
        # override.
        parts = clean.split("/")
        for position in range(1, len(parts)):
            if "/".join(parts[:position]) in excluded_directories:
                included_overrides.append(item)
                break
    traversal: set[str] = set()
    for item in included_overrides:
        parts = item.path.strip("/").split("/")
        for position in range(1, len(parts)):
            traversal.add("/" + "/".join(parts[:position]) + "/")
    lines.extend(f"+ {path}" for path in sorted(traversal))
    lines.extend(f"+ {_pattern(item)}" for item in included_overrides)
    for item in plan.items:
        if item.included:
            continue
        pattern = _pattern(item)
        if item.action in {ChangeAction.DELETE, ChangeAction.DESTINATION_ONLY}:
            lines.append(f"P {pattern}")
        lines.append(f"- {pattern}")
    return lines


_FILTER_TEXT_CACHE: dict[tuple[str, str, str], str] = {}


def filter_text(plan: ExecutionPlan) -> str:
    """The rendered filter file, reused while the plan's contents are equal."""
    key = (plan.items_fingerprint, plan.decision_signature, plan.profile_fingerprint)
    text = _FILTER_TEXT_CACHE.get(key)
    if text is None:
        lines = decision_filter_lines(plan)
        text = "\n".join(lines) + ("\n" if lines else "")
        if len(_FILTER_TEXT_CACHE) >= 4:
            _FILTER_TEXT_CACHE.clear()
        _FILTER_TEXT_CACHE[key] = text
    return text


@contextmanager
def temporary_decision_filter(plan: ExecutionPlan) -> Iterator[Path]:
    descriptor, name = tempfile.mkstemp(prefix="qpy-rsync-plan-", suffix=".rules", text=True)
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(filter_text(plan))
            handle.flush()
            os.fsync(handle.fileno())
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
