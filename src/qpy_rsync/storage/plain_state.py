"""Plain scalar values for the widget state stored in the INI settings file.

Every value written here is ordinary, human-editable text.  There are no Qt
binary blobs and no base64 payloads: a user can open the settings file, change
a number and have the next start pick it up.

The formats are:

* geometry: ``x,y,w,h`` (four integers);
* splitter sizes: ``size,size,...`` (one integer per pane);
* horizontal header state: ``logical:width:hidden,logical:width:hidden,...``
  with one entry per column, ``hidden`` being ``0`` or ``1``.  Keeping one
  entry per logical column preserves both the widths and the visibility of
  columns, including the ones that are currently hidden.

Malformed entries are skipped by the readers so a hand-edited file with a
single bad value cannot discard the rest of the saved state.
"""

from __future__ import annotations

from collections.abc import Iterable
import re

_INTEGER = re.compile(r"[+-]?\d+")
_HEADER_ENTRY = re.compile(r"(\d+):(\d+):([01])")


def ints_to_text(values: Iterable[int]) -> str:
    """Write a list of integers as a comma-separated value."""
    return ",".join(str(int(value)) for value in values)


def text_to_ints(value: object) -> list[int] | None:
    """Read a comma-separated list of integers, or None when it is unusable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    numbers: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not _INTEGER.fullmatch(part):
            return None
        numbers.append(int(part))
    return numbers or None


def header_to_text(entries: Iterable[tuple[int, int, bool]]) -> str:
    """Write ``(logical, width, hidden)`` entries for a horizontal header."""
    return ",".join(
        f"{int(logical)}:{int(width)}:{1 if hidden else 0}"
        for logical, width, hidden in entries
    )


def text_to_header(value: object) -> dict[int, tuple[int, bool]] | None:
    """Read header entries as ``logical -> (width, hidden)``.

    Invalid entries are skipped; a value with no valid entry reads as None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    entries: dict[int, tuple[int, bool]] = {}
    for part in text.split(","):
        match = _HEADER_ENTRY.fullmatch(part.strip())
        if match is None:
            continue
        logical, width, hidden = match.groups()
        entries[int(logical)] = (int(width), hidden == "1")
    return entries or None
