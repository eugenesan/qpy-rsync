from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextLayout, QTextOption
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy


class CommandPreview(QPlainTextEdit):
    """A read-only, wrapping command preview.

    The preview is selectable and scrolls vertically when the command spans
    more lines than it has room for. Word wrapping plus an ignored horizontal
    size hint keeps long commands from widening the main window. Its minimum
    height follows the command, so a single line needs a single line.
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
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._resizing = False
        self.setPlaceholderText("Command preview appears here.")
        self.setText(text)

    def _line_count(self) -> int:
        """Return the number of lines the current text needs."""
        text = self.toPlainText()
        if not text.strip():
            return 1
        layout = QTextLayout(text, self.font())
        layout.beginLayout()
        lines = 0
        width = max(self.viewport().width(), 1)
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines += 1
        layout.endLayout()
        return max(1, lines)

    def _preferred_height(self, lines: int = 1) -> int:
        return self.fontMetrics().lineSpacing() * lines + 12

    def _update_minimum_height(self) -> None:
        if self._resizing:
            return
        self._resizing = True
        try:
            self.setMinimumHeight(self._preferred_height(self._line_count()))
        finally:
            self._resizing = False

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._update_minimum_height()

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.setToolTip(text if text.strip() else "")
        self._update_minimum_height()

    def full_text(self) -> str:
        return self.toPlainText()
