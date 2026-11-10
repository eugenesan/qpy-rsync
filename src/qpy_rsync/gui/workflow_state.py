from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qpy_rsync.core.execution_plan import PlanSummary


class MessageSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


def startup_message(source_present: bool, destination_present: bool) -> str:
    if source_present and destination_present:
        return "Ready. Click Compare to refresh the remembered Source and Destination."
    return "Choose Source and Destination above the comparison panes."


def selected_actions_text(summary: PlanSummary) -> str:
    return (
        f"Selected actions: {summary.included} included, {summary.excluded} unchecked, "
        f"{summary.modified} modified, {summary.retained_destination_only} retained in Destination, "
        f"{summary.destructive} destructive | Backup: "
        f"{'on' if summary.backup_enabled else 'off'}"
    )


def swapped_endpoint_texts(source: str, destination: str) -> tuple[str, str]:
    return destination, source
