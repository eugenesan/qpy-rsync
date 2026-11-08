from __future__ import annotations

import shlex
from pathlib import Path

from PySide6.QtCore import Qt
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
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.services.compare_service import CompareResult, CompareService

from .comparison_view import ComparisonView


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
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        form = QFormLayout()
        self.source_edit = QLineEdit()
        self.destination_edit = QLineEdit()
        form.addRow("Source", self._path_row(self.source_edit))
        form.addRow("Destination", self._path_row(self.destination_edit))
        layout.addLayout(form)

        controls = QHBoxLayout()
        self.compare_button = QPushButton("Compare")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter paths")
        controls.addWidget(self.compare_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(QLabel("Find"))
        controls.addWidget(self.filter_edit, 1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.comparison = ComparisonView()
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
            name="ad-hoc local comparison",
            source=Endpoint(EndpointKind.LOCAL, self.source_edit.text().strip()),
            destination=Endpoint(EndpointKind.LOCAL, self.destination_edit.text().strip()),
        )

    def _compare(self) -> None:
        profile = self._profile()
        if not profile.source.path or not profile.destination.path:
            QMessageBox.warning(self, "Missing paths", "Choose source and destination directories.")
            return
        spec = build_compare_spec(profile)
        self.log.clear()
        self._append_log("$ " + shlex.join(spec.argv()))
        self._service.compare(profile)

    def _comparison_started(self) -> None:
        self.compare_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Comparing...")

    def _comparison_finished(self, result: CompareResult) -> None:
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
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
