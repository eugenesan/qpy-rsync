"""Shared eliding for paths shown outside the comparison grid."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

# The grid elides a filename to the width of its column. Menus and tooltips
# have no column, so they use the same default width the Item column starts
# with (240 px) plus room for indentation.
DEFAULT_PATH_WIDTH = 256


def elide_path(text: str, width: int = DEFAULT_PATH_WIDTH) -> str:
    """Shorten a path for display, keeping the beginning and the end."""
    if not text:
        return ""
    metrics = QFontMetrics(QApplication.font())
    return metrics.elidedText(
        text, Qt.TextElideMode.ElideMiddle, max(1, width)
    )
