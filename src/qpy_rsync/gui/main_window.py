from __future__ import annotations

import shlex
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.core.endpoints import parse_endpoint
from qpy_rsync.core.enums import EndpointKind, Severity
from qpy_rsync.core.models import BackupOptions, FilterRule, SyncProfile
from qpy_rsync.core.validation import validate_profile
from qpy_rsync.services.backup_inspection import inspect_backup_directory
from qpy_rsync.services.compare_service import CompareResult, CompareService
from qpy_rsync.services.diff_tool_service import DiffToolError, build_diff_request

from .comparison_view import ComparisonView
from .filter_editor import FilterEditorDialog
from .backup_settings import decode_backup, encode_backup
from .filter_settings import decode_filters, encode_filters


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("qpy-rsync")
        self.resize(1100, 700)
        self._service = CompareService(self)
        self._service.on_started = self._comparison_started
        self._service.on_finished = self._comparison_finished
        self._service.on_error = self._comparison_error
        self._service.on_log = self._append_log
        self._active_profile: SyncProfile | None = None
        self._filters: list[FilterRule] = []
        self._backup = BackupOptions()
        self._build_ui()
        self._restore_window_state()
        self._restore_endpoints()
        self._restore_filters()
        self._restore_backup()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        form = QFormLayout()
        self.source_edit = QLineEdit()
        self.destination_edit = QLineEdit()
        endpoint_placeholder = "Local: /path or ~/path    SSH: [user@]host:/absolute/path"
        self.source_edit.setPlaceholderText(endpoint_placeholder)
        self.destination_edit.setPlaceholderText(endpoint_placeholder)
        endpoint_help = (
            "Local examples: /home/alice/data or ~/data\n"
            "SSH examples: server:/srv/data or alice@server:/srv/data\n"
            "SSH host aliases from ~/.ssh/config are supported. "
            "At most one endpoint may be remote."
        )
        self.source_edit.setToolTip(endpoint_help)
        self.destination_edit.setToolTip(endpoint_help)
        form.addRow("Source", self._path_row(self.source_edit))
        form.addRow("Destination", self._path_row(self.destination_edit))
        self.backup_edit = QLineEdit()
        self.backup_edit.setPlaceholderText("Empty disables backups")
        self.backup_browse = QPushButton("Browse...")
        self.backup_browse.clicked.connect(self._browse_backup)
        backup_row = QWidget()
        backup_layout = QHBoxLayout(backup_row)
        backup_layout.setContentsMargins(0, 0, 0, 0)
        backup_layout.addWidget(self.backup_edit, 1)
        backup_layout.addWidget(self.backup_browse)
        form.addRow("Backup directory", backup_row)
        self.protect_backup = QCheckBox("Protect nested backup tree")
        self.protect_backup.setChecked(True)
        form.addRow("", self.protect_backup)
        self.backup_status = QLabel("Backups are disabled.")
        self.backup_status.setWordWrap(True)
        form.addRow("Backup status", self.backup_status)
        layout.addLayout(form)
        help_label = QLabel(
            "Locations: local /path or ~/path; SSH [user@]host:/absolute/path. "
            "Directory contents are compared, equivalent to a trailing slash."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        controls = QHBoxLayout()
        self.compare_button = QPushButton("Compare")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.filters_button = QPushButton("Filters...")
        self.filters_label = QLabel("Filters: 0 enabled / 0 total")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter paths")
        controls.addWidget(self.compare_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.filters_button)
        controls.addWidget(self.filters_label)
        controls.addWidget(QLabel("Find"))
        controls.addWidget(self.filter_edit, 1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.comparison = ComparisonView()
        self.comparison.diff_requested.connect(self._open_diff_tool)
        splitter.addWidget(self.comparison)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        splitter.addWidget(self.log)
        splitter.setSizes([520, 130])
        layout.addWidget(splitter, 1)

        self.status_label = QLabel("Ready. Select two local directories.")
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self.compare_button.clicked.connect(self._compare)
        self.cancel_button.clicked.connect(self._service.cancel)
        self.filters_button.clicked.connect(self._edit_filters)
        self.destination_edit.returnPressed.connect(self._compare_if_ready)
        self.source_edit.editingFinished.connect(self._update_command_preview)
        self.destination_edit.editingFinished.connect(self._update_command_preview)
        self.backup_edit.editingFinished.connect(self._backup_changed)
        self.protect_backup.toggled.connect(self._backup_changed)
        self.destination_edit.textChanged.connect(self._update_backup_browse_state)
        self.filter_edit.setEnabled(False)
        self.filter_edit.setToolTip("Path filtering will return with the hierarchical proxy model.")

    def _path_row(self, edit: QLineEdit) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse...")
        button.clicked.connect(lambda: self._browse(edit))
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return container

    def _browse(self, edit: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select directory", edit.text() or str(Path.home()))
        if selected:
            edit.setText(selected + "/")

    def _browse_backup(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select backup directory",
            self.backup_edit.text() or str(Path.home()),
        )
        if selected:
            self.backup_edit.setText(selected)
            self._backup_changed()

    def _update_backup_browse_state(self) -> None:
        try:
            destination = parse_endpoint(self.destination_edit.text())
            self.backup_browse.setEnabled(destination.kind is EndpointKind.LOCAL)
        except ValueError:
            self.backup_browse.setEnabled(False)

    def _profile(self) -> SyncProfile:
        return SyncProfile(
            name="ad-hoc comparison",
            source=parse_endpoint(self.source_edit.text()),
            destination=parse_endpoint(self.destination_edit.text()),
            filters=list(self._filters),
            backup=self._backup,
        )

    def _edit_filters(self) -> None:
        dialog = FilterEditorDialog(self._filters, self)
        if not dialog.exec():
            return
        updated = dialog.rules()
        if updated == self._filters:
            return
        self._filters = updated
        self._save_filters()
        self._update_filter_summary(stale=True)
        self.comparison.set_stale(True)
        self.status_label.setText(
            "Stale comparison: filter rules changed. Compare again to refresh results."
        )

    def _update_filter_summary(self, *, stale: bool = False) -> None:
        enabled = sum(1 for item in self._filters if item.enabled)
        suffix = " | STALE" if stale else ""
        self.filters_label.setText(
            f"Filters: {enabled} enabled / {len(self._filters)} total{suffix}"
        )

    def _backup_changed(self) -> None:
        updated = BackupOptions(
            directory=self.backup_edit.text().strip(),
            protect_nested=self.protect_backup.isChecked(),
        )
        if updated == self._backup:
            self._update_backup_status()
            return
        self._backup = updated
        self._save_backup()
        self._update_backup_status()
        self.comparison.set_stale(True)
        self.status_label.setText(
            "Stale comparison: backup settings changed. Compare again to refresh results."
        )
        self._update_command_preview()

    def _update_command_preview(self) -> None:
        if not self.source_edit.text().strip() or not self.destination_edit.text().strip():
            return
        try:
            spec = build_compare_spec(self._profile())
        except ValueError as exc:
            self.log.clear()
            self._append_log(f"Command preview unavailable: {exc}")
            return
        self.log.clear()
        self._append_log("$ " + shlex.join(spec.argv()))

    def _update_backup_status(self) -> None:
        try:
            profile = self._profile()
            messages = [
                item for item in validate_profile(profile)
                if item.code.startswith("backup.")
            ]
            status = inspect_backup_directory(profile)
        except ValueError as exc:
            self.backup_status.setText(str(exc))
            return
        prefix = ""
        errors = [item.message for item in messages if item.severity is Severity.ERROR]
        warnings = [item.message for item in messages if item.severity is Severity.WARNING]
        if errors:
            prefix = "Error: " + " ".join(errors) + " "
        elif warnings:
            prefix = "Warning: " + " ".join(warnings) + " "
        self.backup_status.setText(prefix + status.message)

    def _compare_if_ready(self) -> None:
        if self.source_edit.text().strip() and self.destination_edit.text().strip():
            self._compare()

    def _compare(self) -> None:
        try:
            profile = self._profile()
            spec = build_compare_spec(profile)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid location", str(exc))
            return
        self.log.clear()
        self._active_profile = profile
        self._save_endpoints()
        self._append_log("$ " + shlex.join(spec.argv()))
        self._service.compare(profile)

    def _open_diff_tool(self, change: object) -> None:
        if self._active_profile is None:
            return
        try:
            request = build_diff_request(self._active_profile, change)  # type: ignore[arg-type]
        except DiffToolError as exc:
            QMessageBox.information(self, "Diff tool unavailable", str(exc))
            return
        arguments = [str(request.source), str(request.destination)]
        started, _pid = QProcess.startDetached(request.tool.executable, arguments)
        if not started:
            QMessageBox.warning(self, "Could not start diff tool", request.tool.executable)
            return
        self._append_log("$ " + shlex.join([request.tool.executable, *arguments]))
        self.status_label.setText(f"Opened {change.path} in {request.tool.name}.")  # type: ignore[attr-defined]

    def _comparison_started(self) -> None:
        self.compare_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Comparing...")

    def _comparison_finished(self, result: CompareResult) -> None:
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.comparison.set_changes(result.parsed.changes)
        self.comparison.set_stale(False)
        for message in result.parsed.diagnostics:
            self._append_log(message)
        count = len(result.parsed.changes)
        self.status_label.setText(f"Comparison complete: {count} changed object(s).")

    def _comparison_error(self, message: str) -> None:
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Comparison failed.")
        self._append_log(message)
        QMessageBox.critical(self, "Comparison failed", message)

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text.rstrip())

    def _save_endpoints(self) -> None:
        settings = QSettings()
        settings.setValue("comparison/source", self.source_edit.text().strip())
        settings.setValue("comparison/destination", self.destination_edit.text().strip())
        settings.sync()

    def _restore_endpoints(self) -> None:
        settings = QSettings()
        self.source_edit.setText(str(settings.value("comparison/source", "")))
        self.destination_edit.setText(str(settings.value("comparison/destination", "")))

    def _save_filters(self) -> None:
        settings = QSettings()
        settings.setValue("comparison/filters", encode_filters(self._filters))
        settings.sync()

    def _restore_filters(self) -> None:
        settings = QSettings()
        payload = str(settings.value("comparison/filters", ""))
        try:
            self._filters = decode_filters(payload)
        except (TypeError, ValueError):
            self._filters = []
            self._append_log("Stored filters were invalid and have been ignored.")
        self._update_filter_summary()

    def _save_backup(self) -> None:
        settings = QSettings()
        settings.setValue("comparison/backup", encode_backup(self._backup))
        settings.sync()

    def _restore_backup(self) -> None:
        settings = QSettings()
        payload = str(settings.value("comparison/backup", ""))
        try:
            self._backup = decode_backup(payload)
        except (KeyError, TypeError, ValueError):
            self._backup = BackupOptions()
            self._append_log("Stored backup settings were invalid and have been ignored.")
        self.backup_edit.setText(self._backup.directory)
        self.protect_backup.setChecked(self._backup.protect_nested)
        self._update_backup_browse_state()
        self._update_backup_status()
        self._update_command_preview()

    def _restore_window_state(self) -> None:
        settings = QSettings()
        geometry = settings.value("main-window/geometry")
        state = settings.value("main-window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        settings = QSettings()
        settings.setValue("main-window/geometry", self.saveGeometry())
        settings.setValue("main-window/state", self.saveState())
        settings.sync()
        self.comparison.save_view_state()
        super().closeEvent(event)  # type: ignore[arg-type]
