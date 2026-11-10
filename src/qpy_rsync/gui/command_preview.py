from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy


class CommandPreview(QPlainTextEdit):
    """A read-only, wrapping command preview.

    The preview is selectable and scrolls vertically when the command spans
    more than the two visible lines. Word wrapping plus an ignored horizontal
    size hint keeps long commands from widening the main window.
    """

    def __init__(self, text: str = "", parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setObjectName("command-preview")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTabChangesFocus(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._preferred_height())
        self.setText(text)

    def _preferred_height(self) -> int:
        return self.fontMetrics().lineSpacing() * 2 + 14

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.setVisible(bool(text.strip()))
        self.setToolTip(text if text.strip() else "")

    def full_text(self) -> str:
        return self.toPlainText()
