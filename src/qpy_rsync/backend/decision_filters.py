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
    included_overrides = [
        item
        for item in plan.items
        if item.included
        and any(
            item.path.strip("/").startswith(directory + "/")
            for directory in excluded_directories
        )
    ]
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
        if item.action in {ChangeAction.DELETE, ChangeAction.DESTINATION_ONLY, ChangeAction.REPLACE}:
            lines.append(f"P {pattern}")
        lines.append(f"- {pattern}")
    return lines


@contextmanager
def temporary_decision_filter(plan: ExecutionPlan) -> Iterator[Path]:
    descriptor, name = tempfile.mkstemp(prefix="qpy-rsync-plan-", suffix=".rules", text=True)
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            lines = decision_filter_lines(plan)
            handle.write("\n".join(lines) + ("\n" if lines else ""))
            handle.flush()
            os.fsync(handle.fileno())
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
