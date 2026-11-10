from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from qpy_rsync.core.changes import ChangeAction

ICON_SIZE = 16

ACCENT = QColor("#0891B2")

ACTION_COLORS: dict[ChangeAction, QColor] = {
    ChangeAction.CREATE: QColor("#208020"),
    ChangeAction.UPDATE_CONTENT: QColor("#1d4ed8"),
    ChangeAction.UPDATE_METADATA: QColor("#1d4ed8"),
    ChangeAction.DELETE: QColor("#b91c1c"),
    ChangeAction.DESTINATION_ONLY: QColor("#a05020"),
    ChangeAction.REPLACE: QColor("#7c3aed"),
    ChangeAction.NO_CHANGE: QColor("#64748b"),
    ChangeAction.MESSAGE: QColor("#64748b"),
}

ACTION_LABELS: dict[ChangeAction, str] = {
    ChangeAction.CREATE: "Create",
    ChangeAction.UPDATE_CONTENT: "Update",
    ChangeAction.UPDATE_METADATA: "Metadata only",
    ChangeAction.DELETE: "Delete",
    ChangeAction.DESTINATION_ONLY: "Keep in Destination",
    ChangeAction.REPLACE: "Replace",
    ChangeAction.NO_CHANGE: "Unchanged",
    ChangeAction.MESSAGE: "Message",
}


def _pixmap() -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def _pen(color: QColor, width: float = 1.6) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _arrow_head(painter: QPainter, tip: QPointF, direction: str, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.setBrush(QBrush(color))
    if direction == "left":
        points = [tip, QPointF(tip.x() + 4.0, tip.y() - 3.0), QPointF(tip.x() + 4.0, tip.y() + 3.0)]
    elif direction == "right":
        points = [tip, QPointF(tip.x() - 4.0, tip.y() - 3.0), QPointF(tip.x() - 4.0, tip.y() + 3.0)]
    elif direction == "up":
        points = [tip, QPointF(tip.x() - 3.0, tip.y() + 4.0), QPointF(tip.x() + 3.0, tip.y() + 4.0)]
    else:
        points = [tip, QPointF(tip.x() - 3.0, tip.y() - 4.0), QPointF(tip.x() + 3.0, tip.y() - 4.0)]
    path = QPainterPath(points[0])
    path.lineTo(points[1])
    path.lineTo(points[2])
    path.closeSubpath()
    painter.drawPath(path)


def _draw_plus(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(8, 3.5), QPointF(8, 12.5))
    painter.drawLine(QPointF(3.5, 8), QPointF(12.5, 8))


def _draw_update(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(8, 12.5), QPointF(8, 4.5))
    _arrow_head(painter, QPointF(8, 3.0), "up", color)


def _draw_metadata(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QRectF(6.9, 3.0, 2.2, 2.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(8, 6.6), QPointF(8, 13.0))


def _draw_delete(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
    painter.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))


def _draw_keep(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(12.0, 8.0), QPointF(4.0, 8.0))
    _arrow_head(painter, QPointF(3.0, 8.0), "left", color)


def _draw_replace(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(3.5, 6.0), QPointF(12.0, 6.0))
    _arrow_head(painter, QPointF(13.0, 6.0), "right", color)
    painter.drawLine(QPointF(12.5, 10.0), QPointF(4.0, 10.0))
    _arrow_head(painter, QPointF(3.0, 10.0), "left", color)


def _draw_unchanged(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(4.0, 6.0), QPointF(12.0, 6.0))
    painter.drawLine(QPointF(4.0, 10.0), QPointF(12.0, 10.0))


def _draw_message(painter: QPainter, color: QColor) -> None:
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(8, 3.0), QPointF(8, 9.5))
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(7.0, 11.0, 2.0, 2.0))


def _draw_folder(painter: QPainter, color: QColor, direction: str) -> None:
    painter.setPen(_pen(QColor("#334155")))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(2.5, 13.0)
    path.lineTo(2.5, 4.0)
    path.lineTo(6.5, 4.0)
    path.lineTo(8.0, 6.0)
    path.lineTo(13.5, 6.0)
    path.lineTo(13.5, 13.0)
    path.closeSubpath()
    painter.drawPath(path)
    painter.setPen(_pen(color))
    painter.drawLine(QPointF(5.5, 9.5), QPointF(10.5, 9.5))
    _arrow_head(painter, QPointF(11.5, 9.5), direction, color)


_DRAWERS = {
    ChangeAction.CREATE: _draw_plus,
    ChangeAction.UPDATE_CONTENT: _draw_update,
    ChangeAction.UPDATE_METADATA: _draw_metadata,
    ChangeAction.DELETE: _draw_delete,
    ChangeAction.DESTINATION_ONLY: _draw_keep,
    ChangeAction.REPLACE: _draw_replace,
    ChangeAction.NO_CHANGE: _draw_unchanged,
    ChangeAction.MESSAGE: _draw_message,
}


def action_icon(action: ChangeAction, *, accent: bool = False) -> QIcon:
    """Return the icon that represents one comparison action.

    ``accent`` recolors the icon with the override accent color.
    """
    color = ACCENT if accent else ACTION_COLORS.get(action, QColor("#64748b"))
    pixmap, painter = _pixmap()
    _DRAWERS.get(action, _draw_unchanged)(painter, color)
    painter.end()
    return QIcon(pixmap)


def unchanged_icon() -> QIcon:
    """Icon used for unchanged objects and for directories present on both sides."""
    return action_icon(ChangeAction.NO_CHANGE)


def source_icon() -> QIcon:
    pixmap, painter = _pixmap()
    _draw_folder(painter, QColor("#1d4ed8"), "right")
    painter.end()
    return QIcon(pixmap)


def destination_icon() -> QIcon:
    pixmap, painter = _pixmap()
    _draw_folder(painter, QColor("#15803d"), "left")
    painter.end()
    return QIcon(pixmap)
