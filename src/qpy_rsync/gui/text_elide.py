"""Shared eliding for paths shown outside the comparison grid."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

# The grid elides a filename to the width of its column. Menus and tooltips
# have no column, so they use the same default width the Item column starts
# with (240 px) plus room for indentation.
DEFAULT_PATH_WIDTH = 256


def wrap_path(text: str, width: int = DEFAULT_PATH_WIDTH, max_lines: int = 2) -> str:
    """Wrap a path over up to ``max_lines`` lines, then elide what is left."""
    if not text:
        return ""
    metrics = QFontMetrics(QApplication.font())
    limit = max(1, width)
    remaining = text
    lines: list[str] = []
    for _ in range(max(1, max_lines) - 1):
        if metrics.horizontalAdvance(remaining) <= limit:
            return "\n".join([*lines, remaining])
        # Prefer to break on a separator so the remaining part stays readable.
        best = 0
        for index, char in enumerate(remaining):
            if metrics.horizontalAdvance(remaining[: index + 1]) > limit:
                break
            if char in "/\\":
                best = index + 1
        if best <= 0:
            break
        lines.append(remaining[:best])
        remaining = remaining[best:].lstrip("/\\")
    lines.append(metrics.elidedText(remaining, Qt.TextElideMode.ElideMiddle, limit))
    return "\n".join(lines)


def elide_path(text: str, width: int = DEFAULT_PATH_WIDTH) -> str:
    """Shorten a path for display, keeping the beginning and the end."""
    if not text:
        return ""
    metrics = QFontMetrics(QApplication.font())
    return metrics.elidedText(
        text, Qt.TextElideMode.ElideMiddle, max(1, width)
    )
