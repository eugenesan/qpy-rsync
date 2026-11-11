import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyleOptionViewItem

from qpy_rsync.gui.comparison_view import ROW_HEIGHT, ComparisonView


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_trees_share_row_height_and_scroll_mode() -> None:
    application = app()
    view = ComparisonView()
    option = QStyleOptionViewItem()
    for tree in (view.source, view.action, view.destination):
        assert tree.uniformRowHeights()
        assert tree.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
        assert (
            tree.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert tree.itemDelegate().sizeHint(option, QModelIndex()).height() == ROW_HEIGHT
    view.close()
    application.processEvents()
