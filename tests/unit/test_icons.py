import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from qpy_rsync.gui import icons


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _themed_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    return QIcon(pixmap)


def test_compare_icon_prefers_the_refresh_structure_theme_icon(monkeypatch) -> None:
    app()
    calls: list[str] = []
    original = icons.QIcon.fromTheme

    def from_theme(name: str) -> QIcon:
        calls.append(name)
        return _themed_icon() if name == "refreshstructure-symbolic" else QIcon()

    monkeypatch.setattr(icons.QIcon, "fromTheme", staticmethod(from_theme))
    assert not icons.compare_icon().isNull()
    monkeypatch.setattr(icons.QIcon, "fromTheme", original)
    assert calls[0] == "refreshstructure-symbolic"


def test_app_menu_icon_prefers_the_open_menu_theme_icon(monkeypatch) -> None:
    app()
    calls: list[str] = []
    original = icons.QIcon.fromTheme

    def from_theme(name: str) -> QIcon:
        calls.append(name)
        return _themed_icon() if name == "open-menu-symbolic" else QIcon()

    monkeypatch.setattr(icons.QIcon, "fromTheme", staticmethod(from_theme))
    icons.app_menu_icon.cache_clear()
    try:
        assert not icons.app_menu_icon().isNull()
    finally:
        icons.app_menu_icon.cache_clear()
        monkeypatch.setattr(icons.QIcon, "fromTheme", original)
    assert calls == ["open-menu-symbolic"]


def test_app_menu_fallback_is_not_a_faded_grey() -> None:
    app()
    assert icons._menu_fallback_color() == QApplication.palette().color(
        QPalette.ColorRole.WindowText
    )
