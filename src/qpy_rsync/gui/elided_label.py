from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    """A label that elides long text instead of widening its parent window."""

    def __init__(self, text: str = "", parent: object | None = None) -> None:
        super().__init__(text, parent)  # type: ignore[arg-type]
        self._full_text = text
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())
        self.setMinimumWidth(0)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.setToolTip(text)
        self._update_elision()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        available = max(0, self.width() - 2)
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available)
        super().setText(elided)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        size = super().minimumSizeHint()
        return QSize(0, size.height())
