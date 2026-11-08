from __future__ import annotations

from enum import StrEnum


class EndpointKind(StrEnum):
    LOCAL = "local"
    SSH = "ssh"


class ConflictPolicy(StrEnum):
    OVERRIDE = "override"
    SKIP = "skip"
    UNSELECT = "unselect"


class DeleteTiming(StrEnum):
    BEFORE = "before"
    DURING = "during"
    DELAY = "delay"
    AFTER = "after"


class BackupMode(StrEnum):
    NONE = "none"
    OVERWRITTEN = "overwritten"
    DELETED = "deleted"
    BOTH = "both"


class FilterRuleType(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    ADVANCED = "advanced"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
