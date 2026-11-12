from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyle

from qpy_rsync.core.changes import ChangeAction

# Icons are drawn on a 16x16 grid and rendered at a larger size so Qt can
# downscale them cleanly for 24px tool buttons and checkboxes.
ICON_SIZE = 64
ICON_GRID = 16

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
    painter.scale(ICON_SIZE / ICON_GRID, ICON_SIZE / ICON_GRID)
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


def _draw_folder(
    painter: QPainter, color: QColor, direction: str | None = None
) -> None:
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
    if direction is None:
        return
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


@lru_cache(maxsize=None)
def action_icon(action: ChangeAction, *, accent: bool = False) -> QIcon:
    """Return the icon that represents one comparison action.

    ``accent`` recolors the icon with the override accent color. Icons are
    cached because they are requested for every painted tree row.
    """
    color = ACCENT if accent else ACTION_COLORS.get(action, QColor("#64748b"))
    pixmap, painter = _pixmap()
    _DRAWERS.get(action, _draw_unchanged)(painter, color)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def swap_icon() -> QIcon:
    """Icon used for the Source/Destination swap button."""
    for name in ("swap-panels-symbolic", "swap-panels"):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    pixmap, painter = _pixmap()
    painter.setPen(_pen(QColor("#1d4ed8")))
    painter.drawLine(QPointF(3.5, 5.5), QPointF(12.0, 5.5))
    _arrow_head(painter, QPointF(13.0, 5.5), "right", QColor("#1d4ed8"))
    painter.drawLine(QPointF(12.5, 10.5), QPointF(4.0, 10.5))
    _arrow_head(painter, QPointF(3.0, 10.5), "left", QColor("#15803d"))
    painter.end()
    return QIcon(pixmap)


def _theme_icon(*names: str, fallback: QStyle.StandardPixmap) -> QIcon:
    """Return the first icon the system theme provides, else a style icon."""
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QApplication.style().standardIcon(fallback)


def source_icon() -> QIcon:
    """The system folder icon of the source side."""
    return _theme_icon(
        "inode-directory-symbolic",
        "inode-directory",
        "folder-open-symbolic",
        "folder-open",
        "folder",
        fallback=QStyle.StandardPixmap.SP_DirOpenIcon,
    )


def compare_icon() -> QIcon:
    """The system icon for the Compare action."""
    return _theme_icon(
        "kr_comparedirs",
        "kr_comparedir",
        "document-compareright",
        "document-compareright-symbolic",
        fallback=QStyle.StandardPixmap.SP_FileDialogContentsView,
    )


def verify_icon() -> QIcon:
    """The system icon for verifying the selected actions."""
    return _theme_icon(
        "answer-symbolic",
        "answer",
        "answer-correct",
        "Answer",
        fallback=QStyle.StandardPixmap.SP_DialogApplyButton,
    )


def verified_icon() -> QIcon:
    """The system icon shown after the actions were verified."""
    return _theme_icon(
        "answer-correct-symbolic",
        "answer-correct",
        "dialog-ok-apply",
        fallback=QStyle.StandardPixmap.SP_DialogApplyButton,
    )


def synchronize_icon() -> QIcon:
    """The system icon that starts the synchronization."""
    return _theme_icon(
        "media-playback-start-symbolic",
        "media-playback-start",
        fallback=QStyle.StandardPixmap.SP_MediaPlay,
    )


def destination_icon() -> QIcon:
    """The system icon of the destination side."""
    return _theme_icon(
        "folder-add-symbolic",
        "folder-add",
        "folder",
        fallback=QStyle.StandardPixmap.SP_DirIcon,
    )


def open_icon() -> QIcon:
    """The system icon for loading a profile."""
    return _theme_icon(
        "document-open", "folder-open", fallback=QStyle.StandardPixmap.SP_DialogOpenButton
    )


def save_icon() -> QIcon:
    """The system icon for saving a profile."""
    return _theme_icon(
        "document-save", fallback=QStyle.StandardPixmap.SP_DialogSaveButton
    )


def folder_open_icon() -> QIcon:
    """The system icon for opening a directory externally."""
    return _theme_icon(
        "folder-open-symbolic",
        "folder-open",
        "inode-directory-symbolic",
        "folder",
        fallback=QStyle.StandardPixmap.SP_DirOpenIcon,
    )


def log_file_icon() -> QIcon:
    """The system icon for opening the log file externally."""
    return _theme_icon(
        "text-x-generic-symbolic",
        "text-x-generic",
        "text-plain",
        fallback=QStyle.StandardPixmap.SP_FileIcon,
    )


def search_icon() -> QIcon:
    """The system icon for the filter field."""
    return _theme_icon("edit-find", fallback=QStyle.StandardPixmap.SP_FileDialogContentsView)


def cancel_icon() -> QIcon:
    """The system icon for cancelling an operation."""
    return _theme_icon(
        "process-stop", "dialog-cancel", fallback=QStyle.StandardPixmap.SP_DialogCancelButton
    )


def pause_icon() -> QIcon:
    """The system icon for pausing an operation."""
    return _theme_icon("media-playback-pause", fallback=QStyle.StandardPixmap.SP_MediaPause)


def filters_icon(*, active: bool = False, stale: bool = False) -> QIcon:
    """The filter icon, with a badge when rules are active or stale."""
    base = _theme_icon(
        "view-filter",
        "view-list-details",
        fallback=QStyle.StandardPixmap.SP_FileDialogDetailedView,
    )
    if not active and not stale:
        return base
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    base.paint(painter, 0, 0, ICON_SIZE, ICON_SIZE)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#f59e0b") if stale else ACCENT))
    painter.drawEllipse(QPointF(50.0, 50.0), 11.0, 11.0)
    painter.end()
    return QIcon(pixmap)


def inventory_mode_icon() -> QIcon:
    """The system icon for the inventory-after-compare toggle."""
    return _theme_icon(
        "view-list-details", "view-list-tree", fallback=QStyle.StandardPixmap.SP_FileDialogListView
    )


# --- item icons -----------------------------------------------------------

FILE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Picture",
        ("jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "tif", "tiff", "heic", "avif"),
    ),
    (
        "Document",
        ("txt", "md", "pdf", "doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp"),
    ),
    (
        "Archive",
        ("zip", "tar", "gz", "bz2", "xz", "zst", "7z", "rar", "iso", "tgz", "deb", "rpm"),
    ),
    (
        "Database",
        ("db", "sqlite", "sqlite3", "sql", "xml", "json", "yaml", "yml", "toml", "ini", "csv", "tsv"),
    ),
    (
        "Executable",
        ("sh", "bash", "py", "pl", "rb", "js", "exe", "bin", "appimage", "so", "run"),
    ),
)

GROUP_COLORS: dict[str, QColor] = {
    "Picture": QColor("#0ea5e9"),
    "Document": QColor("#eab308"),
    "Archive": QColor("#a855f7"),
    "Database": QColor("#14b8a6"),
    "Executable": QColor("#ef4444"),
    "Regular": QColor("#94a3b8"),
    "Folder": QColor("#94a3b8"),
}


def file_group(name: str) -> str:
    """Return the group of a file, based on its extension."""
    extension = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    for group, extensions in FILE_GROUPS:
        if extension in extensions:
            return group
    return "Regular"


def _draw_page(painter: QPainter, color: QColor) -> None:
    """A page with a folded corner, used as the base of every file icon."""
    pen = _pen(color, 1.4)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(4.0, 2.0))
    path.lineTo(9.5, 2.0)
    path.lineTo(12.5, 5.0)
    path.lineTo(12.5, 14.0)
    path.lineTo(4.0, 14.0)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(9.5, 2.0), QPointF(9.5, 5.0))
    painter.drawLine(QPointF(9.5, 5.0), QPointF(12.5, 5.0))


@lru_cache(maxsize=None)
def file_type_icon(name: str) -> QIcon:
    """Icon for a file, coloured by its type group."""
    group = file_group(name)
    color = GROUP_COLORS.get(group, GROUP_COLORS["Regular"])
    pixmap, painter = _pixmap()
    _draw_page(painter, QColor("#94a3b8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawRect(QRectF(5.5, 9.0, 5.5, 2.5))
    painter.end()
    icon = QIcon(pixmap)
    return icon


@lru_cache(maxsize=None)
def folder_icon() -> QIcon:
    """Icon for a folder that exists on one side only."""
    pixmap, painter = _pixmap()
    _draw_folder(painter, QColor("#94a3b8"))
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def folder_limited_icon() -> QIcon:
    """Folder icon with a marker for a folder left collapsed by the limit."""
    pixmap, painter = _pixmap()
    _draw_folder(painter, QColor("#94a3b8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#f59e0b")))
    painter.drawEllipse(QPointF(12.0, 12.0), 3.0, 3.0)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def folder_sync_icon() -> QIcon:
    """Faded equals icon for a folder that exists on both sides."""
    color = QColor("#94a3b8")
    color.setAlpha(150)
    pixmap, painter = _pixmap()
    _draw_unchanged(painter, color)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def folder_sync_changed_icon() -> QIcon:
    """Faded equals icon with an accent dot for a folder that holds changes."""
    color = QColor("#94a3b8")
    color.setAlpha(150)
    pixmap, painter = _pixmap()
    _draw_unchanged(painter, color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(ACCENT))
    painter.drawEllipse(QPointF(12.0, 12.0), 3.0, 3.0)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def unchanged_icon() -> QIcon:
    """Checkmark for an unchanged item (also the inventory button)."""
    return _checkmark_icon(ACTION_COLORS[ChangeAction.NO_CHANGE])


@lru_cache(maxsize=None)
def unchanged_faded_icon() -> QIcon:
    """Faded checkmark, so an unchanged row reads as inactive."""
    color = QColor(ACTION_COLORS[ChangeAction.NO_CHANGE])
    color.setAlpha(120)
    return _checkmark_icon(color)


def _checkmark_icon(color: QColor) -> QIcon:
    pixmap, painter = _pixmap()
    painter.setPen(_pen(color, 2.0))
    painter.drawLine(QPointF(4.0, 8.6), QPointF(6.9, 11.4))
    painter.drawLine(QPointF(6.9, 11.4), QPointF(12.0, 4.8))
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def app_menu_icon() -> QIcon:
    """Hamburger icon of the application menu button."""
    color = QColor("#94a3b8")
    pixmap, painter = _pixmap()
    painter.setPen(_pen(color, 1.8))
    for y in (4.5, 8.0, 11.5):
        painter.drawLine(QPointF(3.5, y), QPointF(12.5, y))
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def settings_icon() -> QIcon:
    """Gear icon for the settings button."""
    color = QColor("#94a3b8")
    pixmap, painter = _pixmap()
    painter.setPen(_pen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(8.0, 8.0), 2.6, 2.6)
    for step in range(8):
        import math

        angle = math.radians(step * 45)
        inner = QPointF(8 + 4.2 * math.cos(angle), 8 + 4.2 * math.sin(angle))
        outer = QPointF(8 + 6.2 * math.cos(angle), 8 + 6.2 * math.sin(angle))
        painter.drawLine(inner, outer)
    painter.end()
    return QIcon(pixmap)
