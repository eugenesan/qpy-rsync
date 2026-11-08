from __future__ import annotations

from dataclasses import dataclass

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

from .rsync_command import ITEM_SEPARATOR


class RsyncParseError(ValueError):
    """Raised when controlled rsync output does not match our contract."""


_TYPE_MAP = {
    "f": ObjectKind.FILE,
    "d": ObjectKind.DIRECTORY,
    "L": ObjectKind.SYMLINK,
    "D": ObjectKind.DEVICE,
    "S": ObjectKind.SPECIAL,
}


@dataclass(slots=True)
class ParseResult:
    changes: list[Change]
    diagnostics: list[str]


def _action(code: str, *, delete_enabled: bool) -> ChangeAction:
    if code.startswith("*deleting"):
        return ChangeAction.DELETE if delete_enabled else ChangeAction.DESTINATION_ONLY
    if len(code) < 11:
        raise RsyncParseError(f"Invalid itemized code: {code!r}")
    attrs = code[2:]
    if "+" in attrs:
        return ChangeAction.CREATE
    if code[0] in {">", "<"} or attrs[0] in {"c", "s"}:
        return ChangeAction.UPDATE_CONTENT
    if any(char not in {".", " "} for char in attrs):
        return ChangeAction.UPDATE_METADATA
    return ChangeAction.NO_CHANGE


def _kind(code: str) -> ObjectKind:
    if code.startswith("*deleting"):
        return ObjectKind.UNKNOWN
    return _TYPE_MAP.get(code[1] if len(code) > 1 else "", ObjectKind.UNKNOWN)


def parse_record(line: str, *, delete_enabled: bool = True) -> Change | None:
    line = line.rstrip("\r\n")
    if not line:
        return None
    if ITEM_SEPARATOR not in line:
        # Rsync can emit non-record informational lines. Keep these out of the
        # change model; callers may display them as diagnostics.
        return None
    parts = line.split(ITEM_SEPARATOR, 3)
    if len(parts) != 4:
        raise RsyncParseError(f"Expected four output fields, got {len(parts)}")
    code, size_text, modified_time, name_and_link = parts
    if ITEM_SEPARATOR in name_and_link:
        raise RsyncParseError("Field separator appears in filename; record is ambiguous")
    if "\x00" in name_and_link:
        raise RsyncParseError("NUL in rsync output is unsupported")
    size: int | None
    if size_text.strip().isdigit():
        size = int(size_text.strip())
    elif code.startswith("*deleting") and not size_text.strip():
        size = None
    else:
        raise RsyncParseError(f"Invalid size field: {size_text!r}")

    link_target = None
    path = name_and_link
    marker = " -> "
    if _kind(code) is ObjectKind.SYMLINK and marker in name_and_link:
        path, link_target = name_and_link.split(marker, 1)
    if not path:
        raise RsyncParseError("Empty change path")

    action = _action(code, delete_enabled=delete_enabled)
    reason = describe_itemized(code)
    return Change(path, action, _kind(code), code, size, modified_time or None, link_target, reason)


def parse_output(text: str, *, strict: bool = True, delete_enabled: bool = True) -> ParseResult:
    changes: list[Change] = []
    diagnostics: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            change = parse_record(line, delete_enabled=delete_enabled)
        except RsyncParseError as exc:
            if strict:
                raise RsyncParseError(f"line {line_number}: {exc}") from exc
            diagnostics.append(f"line {line_number}: {exc}")
            continue
        if change is None:
            if line.strip():
                diagnostics.append(line)
        else:
            changes.append(change)
    return ParseResult(changes, diagnostics)


def describe_itemized(code: str) -> str:
    if code.startswith("*deleting"):
        return "destination-only object will be deleted"
    if len(code) < 11:
        return "unrecognized rsync action"
    attrs = code[2:11]
    reasons: list[str] = []
    labels = (
        (0, "checksum/value"),
        (1, "size"),
        (2, "modification time"),
        (3, "permissions"),
        (4, "owner"),
        (5, "group"),
        (6, "ACL"),
        (7, "extended attributes"),
    )
    if "+" in attrs:
        return "new object"
    for position, label in labels:
        if position < len(attrs) and attrs[position] not in {".", " "}:
            reasons.append(label)
    return ", ".join(reasons) if reasons else "rsync reported a change"
