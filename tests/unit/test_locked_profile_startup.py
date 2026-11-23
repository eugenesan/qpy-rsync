"""Locked profile at startup: temporary copy, cleanup and sync gating."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import ChangeDecision
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.gui.main_window import MainWindow
from qpy_rsync.storage.instance_lock import FileLock
from qpy_rsync.storage.profile_store import save_profile
from qpy_rsync.storage.settings import app_settings, decode_text, profiles_directory


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def profile() -> SyncProfile:
    root = tempfile.gettempdir()
    return SyncProfile(
        "locked",
        Endpoint(EndpointKind.LOCAL, root),
        Endpoint(EndpointKind.LOCAL, root),
    )


def test_locked_profile_uses_temp_copy_without_caching_recent(
    tmp_path: Path, monkeypatch
) -> None:
    application = app()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    target = profiles_directory() / "locked.json"
    save_profile(target, profile())
    # A lock owned by another live PID (PID 1 is always alive).
    lock_path = FileLock(target).lock_path
    lock_path.write_text("1", encoding="ascii")
    settings = app_settings()
    settings.clear()
    from qpy_rsync.storage.settings import encode_text

    settings.setValue("profile/current_path", encode_text(str(target)))
    settings.sync()

    window = MainWindow()
    assert window._temp_profile
    assert window._profile_path != target
    assert Path(
        decode_text(settings.value("profile/current_path", ""))
    ).name == target.name

    temp = window._profile_path
    assert temp is not None and temp.exists()
    log_paths = window._temp_log_paths
    for path in log_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("temp record", encoding="utf-8")

    window._discard_temp_profile()
    assert not temp.exists()
    assert all(not path.exists() for path in log_paths)
    window.close()
    application.processEvents()


def test_finalize_temp_profile_renames_logs(tmp_path: Path, monkeypatch) -> None:
    application = app()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    app_log, rsync_log = window._log_paths_for_profile_name("temp~abc")
    app_log.parent.mkdir(parents=True, exist_ok=True)
    app_log.write_text("app", encoding="utf-8")
    rsync_log.write_text("rsync", encoding="utf-8")
    temp_profile = profiles_directory() / "temp~abc.json"
    save_profile(temp_profile, profile())
    window._temp_profile = True
    window._temp_profile_path = temp_profile
    window._temp_log_paths = (app_log, rsync_log)

    target = profiles_directory() / "saved.json"
    window._finalize_temp_profile(target)
    assert not window._temp_profile
    assert not temp_profile.exists()
    assert (tmp_path / "cache" / "qpy-rsync" / "app-saved.log").read_text() == "app"
    assert (
        tmp_path / "cache" / "qpy-rsync" / "rsync-saved.log"
    ).read_text() == "rsync"
    window.close()
    application.processEvents()


def test_estimated_summary_keeps_sync_enabled() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=10),
        Change("b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=10),
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    window.comparison.model.decisions.set("folder", ChangeDecision.EXCLUDE)
    window._plan_stale = True
    window._refresh_estimated_summary()
    assert window.synchronize_button.isEnabled()
    window.close()
    application.processEvents()


def test_locked_startup_quit_leaves_no_files(tmp_path: Path, monkeypatch) -> None:
    application = app()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    target = profiles_directory() / "locked.json"
    save_profile(target, profile())
    FileLock(target).lock_path.write_text("1", encoding="ascii")

    window = MainWindow()
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")  # exercise the dialog path
    monkeypatch.setattr(
        window, "_choose_locked_profile_option", lambda *_a: ("quit", None, "")
    )
    result = window._prepare_profile_path(profile(), target, startup=True)
    assert result is None
    assert window._startup_abort
    assert window._profile_lock is None
    assert list(profiles_directory().glob("locked~tmp*.json")) == []
    window.close()
    application.processEvents()


def test_locked_startup_retry_continues_when_released(
    tmp_path: Path, monkeypatch
) -> None:
    application = app()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    target = profiles_directory() / "locked.json"
    save_profile(target, profile())
    lock_path = FileLock(target).lock_path
    lock_path.write_text("1", encoding="ascii")

    window = MainWindow()
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")  # exercise the dialog path
    monkeypatch.setattr(
        window, "_choose_locked_profile_option", lambda *_a: ("acquired", None, "")
    )
    lock_path.unlink()
    result = window._prepare_profile_path(profile(), target, startup=True)
    assert result == target
    assert not window._temp_profile
    assert not window._startup_abort
    window.close()
    application.processEvents()


def test_saving_temp_profile_renames_its_logs(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    application = app()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    window = MainWindow()
    temp = profiles_directory() / "locked~tmpabc.json"
    save_profile(temp, profile())
    app_log, rsync_log = window._log_paths_for_profile_name(temp.stem)
    app_log.parent.mkdir(parents=True, exist_ok=True)
    app_log.write_text("kept", encoding="utf-8")
    rsync_log.write_text("kept too", encoding="utf-8")
    window._temp_profile = True
    window._temp_profile_path = temp
    window._temp_log_paths = (app_log, rsync_log)
    window._profile_path = temp
    root = tempfile.gettempdir()
    window.source_edit.setText(root)
    window.destination_edit.setText(root)

    target = profiles_directory() / "kept.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(target), "")),
    )
    assert window._save_profile()
    assert not window._temp_profile
    assert target.exists()
    assert not temp.exists()
    assert not app_log.exists() and not rsync_log.exists()
    assert (
        tmp_path / "cache" / "qpy-rsync" / "app-kept.log"
    ).read_text().startswith("kept")
    assert (
        tmp_path / "cache" / "qpy-rsync" / "rsync-kept.log"
    ).read_text().startswith("kept too")
    assert Path(
        decode_text(app_settings().value("profile/current_path", ""))
    ) == target
    window.close()
    application.processEvents()


def test_locked_dialog_buttons_close_and_return_choices() -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    application = app()
    window = MainWindow()
    locked = profiles_directory() / "locked.json"
    FileLock(locked).lock_path.write_text("1", encoding="ascii")

    def click_when_visible(label: str, after_click: object = None) -> None:
        def click() -> None:
            for widget in application.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    buttons = widget.findChild(QDialogButtonBox)
                    target = next(
                        (b for b in buttons.buttons() if b.text() == label),
                        None,
                    )
                    if target is not None:
                        target.click()
                        if after_click is not None:
                            after_click(widget)
                        return
            QTimer.singleShot(10, click)

        QTimer.singleShot(10, click)

    def check_button_widths(dialog: QDialog) -> None:
        buttons = dialog.findChild(QDialogButtonBox)
        from PySide6.QtWidgets import QPushButton

        width = sum(
            button.sizeHint().width()
            for button in buttons.findChildren(QPushButton)
        )
        assert width <= dialog.width() - 20

    click_when_visible("Use temporary profile", check_button_widths)
    assert window._choose_locked_profile_option(
        locked, "chosen"
    ) == ("temp", None, "chosen")

    click_when_visible("Quit without changes")
    assert window._choose_locked_profile_option(
        locked, "chosen"
    ) == ("quit", None, "")

    # Retry while the lock is held keeps the same dialog open and turns its
    # message orange; the dialog is still running until Quit is pressed.
    def check_status(dialog: QDialog) -> None:
        status = next(
            label
            for label in dialog.findChildren(QLabel)
            if "Still in use" in label.text()
        )
        assert "Still in use" in status.text()
        assert "#EA580C" in status.styleSheet()
        QTimer.singleShot(10, lambda: click_when_visible("Quit without changes"))

    from PySide6.QtWidgets import QLabel

    click_when_visible("Check again", check_status)
    assert window._choose_locked_profile_option(
        locked, "chosen"
    ) == ("quit", None, "")

    window.close()
    application.processEvents()


def test_ctrl_c_closes_modal_startup_dialog(monkeypatch) -> None:
    import signal

    from PySide6.QtWidgets import QDialog

    from qpy_rsync.app import install_interrupt_handler

    application = app()
    previous = signal.getsignal(signal.SIGINT)
    dialog = QDialog()
    dialog.setWindowTitle("Profile already open")
    dialog.show()
    try:
        install_interrupt_handler(application)
        os.kill(os.getpid(), signal.SIGINT)
        for _ in range(10):
            application.processEvents()
        assert not dialog.isVisible()
    finally:
        signal.signal(signal.SIGINT, previous)
        dialog.close()
