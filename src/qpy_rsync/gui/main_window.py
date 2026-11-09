from __future__ import annotations

import shlex
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import (
    QFileDialog,
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
from qpy_rsync.core.models import FilterRule, SyncProfile
from qpy_rsync.services.compare_service import CompareResult, CompareService
from qpy_rsync.services.diff_tool_service import DiffToolError, build_diff_request

from .comparison_view import ComparisonView
from .filter_editor import FilterEditorDialog
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
        self._build_ui()
        self._restore_window_state()
        self._restore_endpoints()
        self._restore_filters()

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

    def _profile(self) -> SyncProfile:
        return SyncProfile(
            name="ad-hoc comparison",
            source=parse_endpoint(self.source_edit.text()),
            destination=parse_endpoint(self.destination_edit.text()),
            filters=list(self._filters),
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
        self.comparison.set_stale(False)
        self.comparison.set_changes(result.parsed.changes)
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
