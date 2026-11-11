from __future__ import annotations

from copy import deepcopy
import shlex
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QProcess, QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QToolTip,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.core.endpoints import parse_endpoint
from qpy_rsync.storage.profile_store import (
    load_profile,
    profile_from_json,
    profile_to_json,
    save_profile,
)
from qpy_rsync.storage.settings import app_settings, decode_binary, encode_binary
from qpy_rsync.core.enums import EndpointKind, Severity, SyncMode
from qpy_rsync.core.backup_paths import resolve_backup
from qpy_rsync.core.execution_gate import ExecutionGate, ExecutionGateState
from qpy_rsync.core.execution_plan import (
    ExecutionPlan,
    build_execution_plan,
    check_plan_freshness,
    profile_fingerprint,
)
from qpy_rsync.core.models import BackupOptions, FilterRule, SyncProfile, TransferOptions
from qpy_rsync.core.validation import validate_profile
from qpy_rsync.services.backup_inspection import inspect_backup_directory
from qpy_rsync.services.compare_service import CompareResult, CompareService
from qpy_rsync.services.diff_tool_service import DiffToolError, build_diff_request
from qpy_rsync.services.inventory_service import InventoryService
from qpy_rsync.services.plan_validation_service import (
    PlanValidationResult,
    PlanValidationService,
    compare_plan_to_changes,
)
from qpy_rsync.services.sync_service import SyncResult, SyncService

from .action_filters import ActionFilterBar
from .command_preview import CommandPreview
from .comparison_view import CONTROL_ICON_SIZE, CONTROL_SIZE, ComparisonView
from .icons import destination_icon, source_icon, swap_icon
from .filter_editor import FilterEditorDialog
from .backup_settings import decode_backup, encode_backup
from .filter_settings import decode_filters, encode_filters
from .sync_confirmation import SyncConfirmationDialog

if TYPE_CHECKING:
    from qpy_rsync.app import StartupOptions


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("qpy-rsync")
        self.resize(1100, 700)
        self._service = CompareService(self)
        self._service.on_started = self._comparison_started
        self._service.on_finished = self._comparison_finished
        self._service.on_error = self._comparison_error
        self._service.on_cancelled = self._comparison_cancelled
        self._service.on_log = self._append_log
        self._service.on_progress = self._comparison_progress
        self._active_profile: SyncProfile | None = None
        self._comparison_profile: SyncProfile | None = None
        self._current_plan: ExecutionPlan | None = None
        self._validated_plan: ExecutionPlan | None = None
        self._execution_gate = ExecutionGate()
        self._plan_validation = PlanValidationService(self)
        self._plan_validation.on_started = self._plan_validation_started
        self._plan_validation.on_finished = self._plan_validation_finished
        self._plan_validation.on_error = self._plan_validation_error
        self._plan_validation.on_cancelled = self._plan_validation_cancelled
        self._plan_validation.on_log = self._append_log
        self._plan_validation.on_spec = self._log_spec
        self._inventory_service = InventoryService(self)
        self._inventory_service.finished.connect(self._inventory_finished)
        self._inventory_service.failed.connect(self._inventory_failed)
        self._inventory_token = 0
        self._inventory_pending_key: object | None = None
        self._inventory_cache_key: object | None = None
        self._inventory_cache: list[object] | None = None
        self._last_changed_changes: list[object] = []
        self._sync_service = SyncService(self)
        self._sync_service.on_started = self._sync_started
        self._sync_service.on_finished = self._sync_finished
        self._sync_service.on_error = self._sync_error
        self._sync_service.on_stdout = self._append_log
        self._sync_service.on_stderr = self._append_log
        self._sync_service.on_progress = self._sync_progress
        self._sync_service.on_spec = self._log_spec
        self._filters: list[FilterRule] = []
        self._backup = BackupOptions()
        self._hovered_action = "compare"
        self._closing = False
        self._log_file_enabled = True
        self._log_file_path = self._default_log_file_path()
        self._log_initialized = False
        self._log_handle = None
        self._log_buffer: list[str] = []
        self._bulk_logging = False
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(100)
        self._log_flush_timer.timeout.connect(self._flush_log)
        self._build_ui()
        self._restore_window_state()
        if not self._restore_recent_profile():
            self._restore_filters()
            self._restore_backup()
        self._restore_logging_settings()
        self._update_startup_status()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        self.source_edit = QLineEdit()
        self.destination_edit = QLineEdit()
        endpoint_placeholder = "Local: /path or ~/path    SSH: [user@]host:/absolute/path"
        self.source_edit.setPlaceholderText(endpoint_placeholder)
        self.destination_edit.setPlaceholderText(endpoint_placeholder)
        endpoint_help = (
            "Local examples: /home/alice/data or ~/data\n"
            "SSH examples: server:/srv/data or alice@server:/srv/data\n"
            "SSH host aliases from ~/.ssh/config are supported. At most one endpoint may be remote."
        )
        self.source_edit.setToolTip(endpoint_help)
        self.destination_edit.setToolTip(endpoint_help)

        self.comparison = ComparisonView()
        self.comparison.diff_requested.connect(self._open_diff_tool)
        self.comparison.decision_changed.connect(self._invalidate_validated_plan)
        self.comparison.controls.setParent(root)

        controls = QHBoxLayout()
        self.sync_mode = QComboBox()
        self.sync_mode.addItem("Update", SyncMode.UPDATE)
        self.sync_mode.addItem("Mirror", SyncMode.MIRROR)
        self.sync_mode.addItem("New Only", SyncMode.NEW_ONLY)
        self.sync_mode.setToolTip(
            "Mode selection\n"
            "Update: copy new and changed objects; keep destination-only objects.\n"
            "Mirror: make Destination match Source, including deletions.\n"
            "New Only: copy missing objects; do not update or delete existing objects."
        )
        controls.addWidget(self.sync_mode)
        self.swap_button = QToolButton()
        self.swap_button.setIcon(swap_icon())
        self.swap_button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.swap_button.setToolTip("Swap Source and Destination")
        self.swap_button.setAccessibleName("Swap Source and Destination")
        self.swap_button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.swap_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.swap_button)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setToolTip(
            "Compare Source and Destination using an rsync dry run.\n"
            "No files are changed.\n"
            "For SSH endpoints this connects to the remote host, so the remote "
            "host must be reachable and credentials must be available."
        )
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.validate_plan_button = QPushButton("Verify Actions")
        self.validate_plan_button.setToolTip(
            "Verify the selected actions.\n"
            "When no checkbox decisions were changed after the comparison, the\n"
            "latest comparison is reused immediately.\n"
            "Otherwise a second rsync dry run checks the selected subset; that run\n"
            "can be cancelled.\n"
            "For SSH endpoints the dry run connects to the remote host again, so the\n"
            "remote host must be reachable and credentials must be available."
        )
        self.synchronize_button = QPushButton("Synchronize...")
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setMinimumWidth(
            max(
                self.validate_plan_button.fontMetrics().horizontalAdvance("Verify Actions"),
                self.validate_plan_button.fontMetrics().horizontalAdvance("Actions Verified"),
            )
            + 28
        )
        self.validate_plan_button.setEnabled(False)
        self.filters_button = QPushButton("Filters")
        self.save_profile_button = QPushButton("Save Profile...")
        self.load_profile_button = QPushButton("Load Profile...")
        self.show_unchanged = self.comparison.inventory_button
        self.show_unchanged.toggled.connect(lambda _checked: self._apply_inventory_mode())
        for widget in (
            self.compare_button,
            self.validate_plan_button,
            self.synchronize_button,
            self.cancel_button,
            self.filters_button,
            self.save_profile_button,
            self.load_profile_button,
        ):
            controls.addWidget(widget)
        controls.addWidget(self.comparison.controls, 1)
        layout.addLayout(controls)

        locations = QHBoxLayout()
        source_panel = self._location_panel("Source", self.source_edit)
        self.action_filters = ActionFilterBar(self)
        self.action_filters.changed.connect(self._apply_action_filters)
        destination_panel = self._location_panel("Destination", self.destination_edit)
        locations.addWidget(source_panel, 40)
        locations.addWidget(self.action_filters, 0, Qt.AlignmentFlag.AlignVCenter)
        locations.addWidget(self.comparison.view_controls, 0, Qt.AlignmentFlag.AlignVCenter)
        locations.addWidget(destination_panel, 40)
        layout.addLayout(locations)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter = splitter
        splitter.addWidget(self.comparison)
        log_panel = QWidget(self)
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(2)
        self.log_header = QLabel("Journal")
        self.log_header.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.status_label = QLabel()
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        # The Journal box absorbs the extra room of its pane. The header keeps
        # its natural height so no gap opens up between the label and the box.
        self.log.setMinimumHeight(32)
        self.log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.command_preview_label = CommandPreview("")
        self.command_preview_label.setObjectName("command-preview-label")
        log_container = QWidget(self)
        log_container.setMinimumHeight(0)
        log_container_layout = QVBoxLayout(log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)
        log_container_layout.setSpacing(2)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        header_row.addWidget(self.log_header)
        header_row.addWidget(self.status_label, 1)
        log_container_layout.addLayout(header_row)
        log_container_layout.addWidget(self.log, 1)
        self.preview_log_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_log_splitter.setChildrenCollapsible(False)
        self.preview_log_splitter.setHandleWidth(6)
        self.preview_log_splitter.setToolTip(
            "Drag the divider to resize the command preview."
        )
        self.preview_log_splitter.addWidget(self.command_preview_label)
        self.preview_log_splitter.addWidget(log_container)
        self.preview_log_splitter.setStretchFactor(0, 0)
        self.preview_log_splitter.setStretchFactor(1, 1)
        self.preview_log_splitter.setSizes(
            [self.command_preview_label.minimumHeight(), 110]
        )
        log_layout.addWidget(self.progress_bar)
        log_layout.addWidget(self.progress_label)
        log_layout.addWidget(self.preview_log_splitter, 1)
        splitter.addWidget(log_panel)
        splitter.setSizes([380, 250])
        layout.addWidget(splitter, 1)

        backup_panel = QWidget(self)
        backup_layout = QVBoxLayout(backup_panel)
        backup_layout.setContentsMargins(0, 2, 0, 2)
        backup_row = QHBoxLayout()
        backup_group = QWidget(self)
        backup_group_layout = QHBoxLayout(backup_group)
        backup_group_layout.setContentsMargins(0, 0, 0, 0)
        self.backup_edit = QLineEdit()
        self.backup_edit.setPlaceholderText("Empty disables backups")
        self.backup_browse = QPushButton("Browse...")
        self.protect_backup = QCheckBox("Protect nested")
        self.protect_backup.setChecked(True)
        backup_group_layout.addWidget(QLabel("Backup"))
        backup_group_layout.addWidget(self.backup_edit, 1)
        backup_group_layout.addWidget(self.backup_browse)
        backup_group_layout.addWidget(self.protect_backup)

        log_group = QWidget(self)
        log_group_layout = QHBoxLayout(log_group)
        log_group_layout.setContentsMargins(0, 0, 0, 0)
        self.log_file_checkbox = QCheckBox("")
        self.log_file_checkbox.setChecked(True)
        self.log_file_edit = QLineEdit(str(self._log_file_path))
        self.log_file_browse = QPushButton("Browse...")
        log_group_layout.addWidget(QLabel("Log"))
        log_group_layout.addWidget(self.log_file_edit, 1)
        log_group_layout.addWidget(self.log_file_browse)
        log_group_layout.addWidget(self.log_file_checkbox)
        log_group_layout.addWidget(QLabel("Enable logging"))

        backup_row.addWidget(backup_group, 1)
        backup_row.addWidget(log_group, 1)
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_panel)

        self.plan_summary_label = QLabel()
        self.plan_summary_label.hide()
        layout.addWidget(self.plan_summary_label)
        self.setCentralWidget(root)

        self.compare_button.clicked.connect(self._compare)
        self.sync_mode.currentIndexChanged.connect(self._sync_mode_changed)
        self.cancel_button.clicked.connect(self._cancel_active_operation)
        self.validate_plan_button.clicked.connect(self._validate_selected_plan)
        self.synchronize_button.clicked.connect(self._show_sync_confirmation)
        self.swap_button.clicked.connect(self._swap_endpoints)
        self.filters_button.clicked.connect(self._edit_filters)
        self.save_profile_button.clicked.connect(self._save_profile)
        self.load_profile_button.clicked.connect(self._load_profile)
        self.backup_browse.clicked.connect(self._browse_backup)
        for button, action in (
            (self.compare_button, "compare"),
            (self.validate_plan_button, "verify"),
            (self.synchronize_button, "synchronize"),
        ):
            button.installEventFilter(self)
            button.setProperty("previewAction", action)
        self.destination_edit.returnPressed.connect(self._compare_if_ready)
        self.source_edit.editingFinished.connect(self._update_command_preview)
        self.destination_edit.editingFinished.connect(self._update_command_preview)
        self.source_edit.textChanged.connect(self._endpoint_text_changed)
        self.destination_edit.textChanged.connect(self._endpoint_text_changed)
        self.backup_edit.editingFinished.connect(self._backup_changed)
        self.protect_backup.toggled.connect(self._backup_changed)
        self.log_file_checkbox.toggled.connect(self._logging_settings_changed)
        self.log_file_edit.editingFinished.connect(self._logging_settings_changed)
        self.log_file_browse.clicked.connect(self._browse_log_file)

    def apply_startup_options(self, options: "StartupOptions") -> None:
        """Apply one-launch command-line overrides after stored settings load."""
        if options.source is not None and options.destination is not None:
            self.source_edit.blockSignals(True)
            self.destination_edit.blockSignals(True)
            self.source_edit.setText(options.source)
            self.destination_edit.setText(options.destination)
            self.source_edit.blockSignals(False)
            self.destination_edit.blockSignals(False)
        if options.mode is not None:
            index = self.sync_mode.findData(options.mode)
            if index < 0:
                raise ValueError(f"Unsupported synchronization mode: {options.mode.value}")
            self.sync_mode.blockSignals(True)
            self.sync_mode.setCurrentIndex(index)
            self.sync_mode.blockSignals(False)
        if options.logging_enabled is not None:
            self.log_file_checkbox.setChecked(options.logging_enabled)
        if options.log_file is not None:
            self.log_file_edit.setText(options.log_file)
            self.log_file_checkbox.setChecked(True)
        self._logging_settings_changed(save=False)
        if options.backup is not None:
            self.backup_edit.blockSignals(True)
            self.protect_backup.blockSignals(True)
            self.backup_edit.setText(options.backup)
            self._backup = BackupOptions(
                directory=options.backup.strip(),
                protect_nested=self.protect_backup.isChecked(),
            )
            self.backup_edit.blockSignals(False)
            self.protect_backup.blockSignals(False)
        self._update_backup_browse_state()
        self._update_backup_status()
        self._update_command_preview()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None
        if options.source is not None and options.destination is not None:
            self._set_status(
                "Command-line Source and Destination loaded."
                + (" Comparison will start automatically." if options.compare else " Click Compare to continue.")
            )
        if options.compare:
            QTimer.singleShot(0, self._compare)

    def _location_panel(self, title: str, edit: QLineEdit) -> QWidget:
        panel = QWidget(self)
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        icon = QLabel()
        icon.setPixmap(
            (source_icon() if title == "Source" else destination_icon()).pixmap(
                CONTROL_ICON_SIZE, CONTROL_ICON_SIZE
            )
        )
        # The label matches the height of the buttons in the same row while the
        # glyph keeps the icon size used everywhere else in the application.
        icon.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName(f"{title.lower()}-location-label")
        icon.setToolTip(f"{title} directory")
        icon.setAccessibleName(f"{title} directory")
        row.addWidget(icon)
        browse = QPushButton("Browse...")
        browse.setToolTip(f"Select the {title} directory")
        browse.clicked.connect(lambda: self._browse(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return panel

    def _path_row(self, edit: QLineEdit) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse...")
        button.clicked.connect(lambda: self._browse(edit))
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return container

    @staticmethod
    def _default_log_file_path() -> Path:
        state_home = os.environ.get("XDG_STATE_HOME", "").strip()
        root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
        return root / "qpy-rsync.log"

    def _restore_logging_settings(self) -> None:
        settings = app_settings()
        self._log_file_enabled = settings.value("logging/enabled", True, type=bool)
        stored = str(settings.value("logging/path", str(self._default_log_file_path())))
        self._log_file_path = Path(stored).expanduser()
        self.log_file_checkbox.blockSignals(True)
        self.log_file_edit.blockSignals(True)
        self.log_file_checkbox.setChecked(self._log_file_enabled)
        self.log_file_edit.setText(str(self._log_file_path))
        self.log_file_checkbox.blockSignals(False)
        self.log_file_edit.blockSignals(False)
        self._update_logging_controls()

    def _logging_settings_changed(self, _checked: bool | None = None, *, save: bool = True) -> None:
        self._flush_log()
        self._close_session_log()
        self._log_file_enabled = self.log_file_checkbox.isChecked()
        value = self.log_file_edit.text().strip()
        self._log_file_path = Path(value).expanduser() if value else self._default_log_file_path()
        if not value:
            self.log_file_edit.setText(str(self._log_file_path))
        self._update_logging_controls()
        if save:
            settings = app_settings()
            settings.setValue("logging/enabled", self._log_file_enabled)
            settings.setValue("logging/path", str(self._log_file_path))
            settings.sync()

    def _update_logging_controls(self) -> None:
        enabled = self.log_file_checkbox.isChecked()
        self.log_file_edit.setEnabled(enabled)
        self.log_file_browse.setEnabled(enabled)

    def _browse_log_file(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Select session log",
            str(self._log_file_path),
            "Log files (*.log);;All files (*)",
        )
        if selected:
            self.log_file_edit.setText(selected)
            self._logging_settings_changed()

    def _open_session_log(self):
        if self._log_handle is not None:
            return self._log_handle
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self._log_file_path.open("a", encoding="utf-8")
        self._log_handle.write(
            f"\n===== qpy-rsync session {datetime.now(timezone.utc).isoformat()} =====\n"
        )
        self._log_handle.flush()
        self._log_initialized = True
        return self._log_handle

    def _close_session_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.flush()
            finally:
                self._log_handle.close()
                self._log_handle = None
        self._log_initialized = False

    def _write_session_log(self, text: str) -> None:
        if not self._log_file_enabled:
            return
        handle = self._open_session_log()
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for line in text.splitlines() or [""]:
            handle.write(f"{timestamp} {line}\n")
        # Buffered writes avoid one fsync (and one open/close) per rsync line.
        handle.flush()

    @staticmethod
    def _browse_start_directory(value: str) -> str:
        text = value.strip()
        try:
            endpoint = parse_endpoint(text)
        except ValueError:
            endpoint = None
        if endpoint is not None and endpoint.kind is EndpointKind.SSH:
            return str(Path.home())
        candidate = Path(text or Path.home()).expanduser()
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        if candidate.exists() and candidate.is_file():
            candidate = candidate.parent
        return str(candidate if candidate.exists() else Path.home())

    def _browse(self, edit: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select directory", self._browse_start_directory(edit.text()))
        if selected:
            edit.setText(selected + "/")

    def _browse_backup(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select backup directory",
            self._browse_start_directory(self.backup_edit.text()),
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

    def _endpoint_text_changed(self) -> None:
        self._update_backup_browse_state()
        if self.comparison.model.changes:
            self.comparison.set_stale(True)
            self._invalidate_plan_context()
            self._set_status(
                "Comparison is out of date because a location changed. Click Compare to refresh.",
                "warning",
            )

    def _swap_endpoints(self) -> None:
        source = self.source_edit.text()
        self.source_edit.blockSignals(True)
        self.destination_edit.blockSignals(True)
        self.source_edit.setText(self.destination_edit.text())
        self.destination_edit.setText(source)
        self.source_edit.blockSignals(False)
        self.destination_edit.blockSignals(False)
        self._save_recent_profile()
        self._update_backup_browse_state()
        self._update_backup_status()
        if self.comparison.model.changes:
            self.comparison.set_stale(True)
            self._set_locations_stale(True)
            self._invalidate_plan_context()
            self._set_status(
                "Source and Destination were swapped. The disabled comparison uses the old direction; click Compare to refresh.",
                "warning",
            )
        else:
            self._update_startup_status()
        self._update_command_preview()

    def _set_locations_stale(self, stale: bool) -> None:
        style = "color: #0891B2;" if stale else ""
        self.source_edit.setStyleSheet(style)
        self.destination_edit.setStyleSheet(style)

    def _set_status(self, text: str, severity: str = "info") -> None:
        colors = {"warning": "#0891B2", "error": "#B91C1C", "success": "#15803D"}
        lines = [part.strip() for part in text.replace(". ", ".\n").splitlines() if part.strip()]
        self.status_label.setToolTip("\n".join(lines))
        color = colors.get(severity, "")
        if color:
            self.status_label.setTextFormat(Qt.TextFormat.RichText)
            self.status_label.setText(f'<span style="color:{color};">{text}</span>')
        else:
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setText(text)
        self._append_log(f"STATUS {text}")

    def _set_backup_message(self, text: str, severity: str = "info") -> None:
        if severity == "info" and text.startswith("Backups are disabled"):
            return
        colors = {"warning": "#0891B2", "error": "#B91C1C", "success": "#15803D"}
        shortened = text.replace("Backups are disabled.", "").strip()
        if shortened:
            self._set_status(shortened, severity if severity != "success" else "info")

    def _update_nested_protection_ui(self, profile: SyncProfile) -> None:
        resolved = resolve_backup(profile)
        nested = bool(resolved and (resolved.nested_in_source or resolved.nested_in_destination))
        self.protect_backup.blockSignals(True)
        if not nested:
            self.protect_backup.setChecked(True)
        self.protect_backup.setEnabled(nested)
        self.protect_backup.blockSignals(False)
        self.protect_backup.setToolTip(
            "Exclude the nested backup directory from synchronization and protect it from deletion."
            if nested
            else "Protection is only needed when the backup directory is inside Source or Destination."
        )

    def _profile(self) -> SyncProfile:
        return SyncProfile(
            name="ad-hoc comparison",
            source=parse_endpoint(self.source_edit.text()),
            destination=parse_endpoint(self.destination_edit.text()),
            filters=list(self._filters),
            backup=self._backup,
            transfer=TransferOptions(sync_mode=SyncMode(self.sync_mode.currentData())),
        )

    def _sync_mode_changed(self) -> None:
        mode = self.sync_mode.currentData()
        if self.comparison.model.changes:
            self.comparison.set_stale(True)
            self._invalidate_plan_context()
            self._set_status(
                "Synchronization mode changed. The visible comparison is out of date; click Compare to refresh.",
                "error" if mode is SyncMode.MIRROR else "warning",
            )
        elif mode is SyncMode.MIRROR:
            self._set_status(
                "Mirror can delete objects that exist only in Destination. Click Compare and review deletions.",
                "error",
            )
        self._update_command_preview()

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
        self._invalidate_plan_context()
        self.status_label.setText(
            "Stale comparison: filter rules changed. Compare again to refresh results."
        )

    def _save_profile(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self, "Save Profile", str(Path.home() / "qpy-rsync-profile.json"), "JSON (*.json)"
        )
        if not path:
            return
        save_profile(Path(path), self._profile())
        self._save_recent_profile()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None
        self._append_log(f"Profile saved: {path}")

    def _load_profile(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Load Profile", str(Path.home()), "JSON (*.json)"
        )
        if not path:
            return
        profile = load_profile(Path(path))
        self._apply_profile(profile)
        self._save_recent_profile()
        self._baseline_profile = self._profile()
        self._append_log(f"Profile loaded: {path}")

    def _apply_profile(self, profile: SyncProfile) -> None:
        self.source_edit.setText(profile.source.path)
        self.destination_edit.setText(profile.destination.path)
        index = self.sync_mode.findData(profile.transfer.sync_mode)
        if index >= 0:
            self.sync_mode.setCurrentIndex(index)
        self.backup_edit.setText(profile.backup.directory)
        self.protect_backup.setChecked(profile.backup.protect_nested)
        self._filters = list(profile.filters)
        self._save_filters()
        self._update_filter_summary(stale=False)
        self._update_backup_status()
        self._update_command_preview()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

    def _update_filter_summary(self, *, stale: bool = False) -> None:
        enabled = sum(1 for item in self._filters if item.enabled)
        total = len(self._filters)
        if total:
            self.filters_button.setText(f"Filters [{enabled}/{total}]")
        else:
            self.filters_button.setText("Filters")
        tooltip = (
            f"{enabled} of {total} persistent filter rules are enabled.\n"
            "The first matching rsync rule wins."
        )
        if stale:
            tooltip += (
                "\n\nSTALE: the comparison is out of date because filter rules changed. "
                "Compare again to refresh results."
            )
        self.filters_button.setToolTip(tooltip)
        self.filters_button.setStyleSheet("color: #0891B2;" if stale else "")

    def _backup_changed(self) -> None:
        updated = BackupOptions(
            directory=self.backup_edit.text().strip(),
            protect_nested=self.protect_backup.isChecked(),
        )
        if updated == self._backup:
            self._update_backup_status()
            return
        self._backup = updated
        self._save_recent_profile()
        self._update_backup_status()
        self._validated_plan = None
        self.validate_plan_button.setText("Verify Actions")
        if self._active_profile is not None and self.comparison.model.changes:
            self._active_profile.backup = BackupOptions(
                directory=updated.directory,
                protect_nested=updated.protect_nested,
            )
            self._refresh_plan_summary()
            self._set_status(
                "Backup settings changed. Verify selected actions again before synchronization.",
                "warning",
            )
        self._update_command_preview()

    def _update_command_preview(self) -> None:
        """Refresh the command preview shown in the progress pane.

        The preview reflects the operation the pointer is over: Compare,
        Verify Actions, or Synchronize.
        """
        if not self.source_edit.text().strip() or not self.destination_edit.text().strip():
            self.command_preview_label.setText("")
            return
        try:
            spec = self._preview_spec()
        except ValueError as exc:
            self.command_preview_label.setText(f"Command preview unavailable: {exc}")
            return
        self.command_preview_label.setText("$ " + shlex.join(spec.argv()))

    def _preview_spec(self):
        action = self._hovered_action
        profile = self._profile()
        if action == "verify":
            return build_compare_spec(profile, filter_file=Path("<decision filter>"))
        if action == "synchronize":
            effective = deepcopy(profile)
            effective.transfer.delete = any(
                item.included and item.action is ChangeAction.DELETE
                for item in (self._current_plan.items if self._current_plan else ())
            )
            return build_sync_spec(effective, filter_file=Path("<decision filter>"))
        return build_compare_spec(profile)

    def _set_hovered_action(self, action: str) -> None:
        if self._hovered_action == action:
            return
        self._hovered_action = action
        self._update_command_preview()

    def _update_backup_status(self) -> None:
        if not self.source_edit.text().strip() or not self.destination_edit.text().strip():
            return
        try:
            profile = self._profile()
            messages = [
                item for item in validate_profile(profile)
                if item.code.startswith("backup.")
            ]
            status = inspect_backup_directory(profile)
        except ValueError as exc:
            self._set_status(str(exc), "error")
            return
        self._update_nested_protection_ui(profile)
        errors = [item.message for item in messages if item.severity is Severity.ERROR]
        warnings = [item.message for item in messages if item.severity is Severity.WARNING]
        if errors:
            self._set_backup_message("Error: " + " ".join(errors) + " " + status.message, "error")
        elif warnings:
            severity = "error" if any(item.code == "backup.directory.unprotected" for item in messages) else "warning"
            self._set_backup_message("Warning: " + " ".join(warnings) + " " + status.message, severity)
        else:
            self._set_backup_message(status.message, "success" if status.nonempty is False else "info")

    def _invalidate_plan_context(self) -> None:
        self._execution_gate.invalidate()
        self.synchronize_button.setEnabled(False)
        self._current_plan = None
        self._validated_plan = None
        self.validate_plan_button.setEnabled(False)
        self.validate_plan_button.setText("Verify Actions")
        self.plan_summary_label.hide()

    def _invalidate_validated_plan(self) -> None:
        self._validated_plan = None
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setText("Verify Actions")
        if self._active_profile is not None and self.comparison.model.changes:
            self._refresh_plan_summary()

    def _refresh_plan_summary(self) -> None:
        if self._active_profile is None:
            self._current_plan = None
            self.plan_summary_label.setText("")
            self.validate_plan_button.setEnabled(False)
            return
        self._current_plan = build_execution_plan(
            self._active_profile,
            self.comparison.model.changes,
            self.comparison.model.decisions,
        )
        summary = self._current_plan.summary
        self.plan_summary_label.setText(
            "Selected actions: "
            f"{summary.included} included, {summary.excluded} unchecked, "
            f"{summary.modified} modified, "
            f"{summary.retained_destination_only} retained in Destination, "
            f"{summary.destructive} destructive; "
            f"create {summary.creates}, update {summary.updates}, "
            f"metadata {summary.metadata}, replace {summary.replacements}, "
            f"delete {summary.deletions}; "
            f"backup {'on' if summary.backup_enabled else 'off'}"
        )
        self.plan_summary_label.show()
        self.validate_plan_button.setEnabled(summary.included > 0)
        self.synchronize_button.setEnabled(False)
        self._execution_gate.selection_changed(included=summary.included)

    def _validate_selected_plan(self) -> None:
        if self._current_plan is None or self._active_profile is None:
            return
        freshness = check_plan_freshness(
            self._current_plan,
            self._profile(),
            self.comparison.model.changes,
        )
        if not freshness.fresh:
            self._validated_plan = None
            QMessageBox.warning(
                self,
                "Execution plan is stale",
                "Plan validation is blocked: " + "; ".join(freshness.reasons),
            )
            return
        if not self.comparison.model.decisions.has_explicit():
            # The comparison already itemized exactly this selection, so a second
            # identical rsync dry run would add no information. Reuse the parsed
            # result; modified decisions still take the full validation path.
            self._plan_validation_started()
            mismatch = compare_plan_to_changes(
                self._current_plan, self.comparison.model.changes
            )
            self._append_log("STATE verification-reused-comparison")
            self._plan_validation_finished(
                PlanValidationResult(mismatch.valid, mismatch, "", 0)
            )
            return
        self._plan_validation.validate(self._active_profile, self._current_plan)

    def _plan_validation_started(self) -> None:
        self._begin_bulk_logging()
        self._set_hovered_action("verify")
        self._execution_gate.verification_started()
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(False)
        self.validate_plan_button.setText("Verifying...")
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Verifying selected actions...")
        self._append_log("STATE verifying-selected-actions")

    def _plan_validation_finished(self, result: PlanValidationResult) -> None:
        if self._closing:
            return
        self.cancel_button.setEnabled(False)
        self.validate_plan_button.setEnabled(True)
        self.validate_plan_button.setText("Verify Actions")
        if result.valid:
            self._validated_plan = self._current_plan
            self._execution_gate.verification_succeeded()
            self.synchronize_button.setEnabled(True)
            self.validate_plan_button.setText("Actions Verified")
            self.status_label.setText("Selected actions verified. No files were changed.")
            self._append_log("STATE actions-verified")
            self._end_bulk_logging()
            return
        self._validated_plan = None
        self._execution_gate.verification_failed()
        self.synchronize_button.setEnabled(False)
        missing = "\n".join(
            f"Missing: {path} ({action.value}, {kind})"
            for path, action, kind in result.mismatch.missing
        )
        unexpected = "\n".join(
            f"Unexpected: {path} ({action.value}, {kind})"
            for path, action, kind in result.mismatch.unexpected
        )
        detail = "\n".join(part for part in (missing, unexpected) if part)
        self._end_bulk_logging()
        QMessageBox.critical(self, "Plan validation mismatch", detail or "Validation result differed from the selected plan.")
        self.status_label.setText("Plan validation failed; synchronization remains blocked.")

    def _plan_validation_cancelled(self) -> None:
        if self._closing:
            return
        self.cancel_button.setEnabled(False)
        self._validated_plan = None
        if self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._execution_gate.verification_failed()
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(self._current_plan is not None)
        self.validate_plan_button.setText("Verify Actions")
        self.status_label.setText("Action verification was cancelled.")
        self._append_log("STATE verification-cancelled")
        self._end_bulk_logging()

    def _plan_validation_error(self, message: str) -> None:
        self.cancel_button.setEnabled(False)
        self._validated_plan = None
        if self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._execution_gate.verification_failed()
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(self._current_plan is not None)
        self.validate_plan_button.setText("Verify Actions")
        self.status_label.setText("Plan validation failed.")
        self._append_log(message)
        self._end_bulk_logging()
        QMessageBox.critical(self, "Plan validation failed", message)

    def _show_sync_confirmation(self) -> None:
        if (
            self._validated_plan is None
            or self._active_profile is None
            or self._execution_gate.state is not ExecutionGateState.VERIFIED
        ):
            QMessageBox.warning(
                self,
                "Verification required",
                "Verify the current selected actions before synchronization.",
            )
            return
        freshness = check_plan_freshness(
            self._validated_plan,
            self._profile(),
            self.comparison.model.changes,
        )
        if not freshness.fresh:
            self._invalidate_validated_plan()
            QMessageBox.warning(
                self,
                "Selected actions are out of date",
                "Compare and verify again: " + "; ".join(freshness.reasons),
            )
            return
        self._execution_gate.confirmation_opened()
        dialog = SyncConfirmationDialog(self._active_profile, self._validated_plan, self)
        accepted = bool(dialog.exec())
        if not accepted:
            self._execution_gate.confirmation_cancelled()
            self.synchronize_button.setEnabled(True)
            return
        try:
            self._sync_service.synchronize(self._active_profile, self._validated_plan)
        except ValueError as exc:
            self._execution_gate.confirmation_cancelled()
            self.synchronize_button.setEnabled(True)
            QMessageBox.critical(self, "Synchronization blocked", str(exc))

    def _cancel_active_operation(self) -> None:
        if self._execution_gate.state is ExecutionGateState.EXECUTING:
            self._sync_service.cancel()
        elif self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._plan_validation.cancel()
        else:
            self._service.cancel()

    def _set_busy_controls(self, busy: bool) -> None:
        self.compare_button.setEnabled(not busy)
        self.validate_plan_button.setEnabled(False if busy else self._current_plan is not None)
        self.synchronize_button.setEnabled(False)
        self.swap_button.setEnabled(not busy)
        self.filters_button.setEnabled(not busy)
        self.sync_mode.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        self.destination_edit.setEnabled(not busy)
        self.backup_edit.setEnabled(not busy)
        self.backup_browse.setEnabled(not busy and self.backup_browse.isEnabled())
        self.protect_backup.setEnabled(not busy and self.protect_backup.isEnabled())
        self.cancel_button.setEnabled(busy)

    def _sync_started(self) -> None:
        self._begin_bulk_logging()
        self._set_hovered_action("synchronize")
        self._execution_gate.execution_started()
        self._set_busy_controls(True)
        self.comparison.set_stale(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Synchronizing...")
        self._set_status("Synchronization is running. The selected actions are applied now.", "warning")
        self._append_log("STATE synchronization-started")

    def _sync_progress(self, progress: object) -> None:
        if self._closing:
            return
        percent = getattr(progress, "percent", 0)
        completed = getattr(progress, "files_completed", 0)
        remaining = getattr(progress, "files_remaining", 0)
        self.progress_bar.setValue(int(percent))
        self.progress_label.setText(
            f"Synchronizing... {int(percent)}% ({completed} files completed, {remaining} remaining)"
        )
        self._append_log(
            f"STATE synchronization-progress percent={int(percent)} "
            f"files_completed={completed} files_remaining={remaining}"
        )

    def _sync_finished(self, result: SyncResult) -> None:
        if self._closing:
            return
        self.progress_bar.setValue(100)
        self.progress_label.setText("Synchronization completed")
        self._execution_gate.execution_completed()
        self._append_log(
            f"STATE synchronization-completed exit_code={result.exit_code}"
        )
        self._end_bulk_logging()
        self._set_busy_controls(False)
        self._validated_plan = None
        self._current_plan = None
        self.plan_summary_label.hide()
        self._set_status(
            f"Synchronization completed with rsync status {result.exit_code}. Refreshing comparison...",
            "success",
        )
        QTimer.singleShot(0, self._compare)

    def _sync_error(self, message: str, cancelled: bool = False) -> None:
        if self._closing:
            return
        if self._execution_gate.state is ExecutionGateState.EXECUTING:
            if cancelled:
                self._execution_gate.execution_cancelled()
            else:
                self._execution_gate.execution_failed()
        self._append_log(
            "STATE synchronization-cancelled"
            if cancelled
            else "STATE synchronization-failed"
        )
        self._set_busy_controls(False)
        self.comparison.set_stale(True)
        self._invalidate_plan_context()
        self._append_log(message)
        self._end_bulk_logging()
        self._set_status(
            "Synchronization was cancelled; compare again before retrying."
            if cancelled
            else "Synchronization failed; review diagnostics and compare again.",
            "error",
        )
        if not cancelled:
            QMessageBox.critical(self, "Synchronization failed", message)

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
        self._flush_log()
        self.log.clear()
        self._active_profile = profile
        self._comparison_profile = profile
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
        self._begin_bulk_logging()
        self._set_hovered_action("compare")
        self._inventory_service.cancel()
        self._inventory_token = 0
        self._inventory_pending_key = None
        self.compare_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Comparing...")
        self.status_label.setText("Comparing...")
        self._append_log("STATE comparing")

    def _comparison_progress(self, progress: object) -> None:
        percent = int(getattr(progress, "percent", 0))
        completed = int(getattr(progress, "files_completed", 0))
        remaining = int(getattr(progress, "files_remaining", 0))
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            f"Comparing... {percent}% ({completed} files inspected, {remaining} remaining)"
        )

    def _comparison_cancelled(self) -> None:
        if self._closing:
            return
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Comparison cancelled")
        self._set_status("Comparison was cancelled. The previous comparison was left unchanged.", "warning")
        self._append_log("STATE comparison-cancelled")
        self._end_bulk_logging()

    def _comparison_finished(self, result: CompareResult) -> None:
        if self._closing:
            return
        self._save_recent_profile()
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_label.setText("Comparison completed")
        self._last_changed_changes = list(result.parsed.changes)
        self.comparison.source_root = self._active_profile.source.path.rstrip("/")
        self.comparison.destination_root = self._active_profile.destination.path.rstrip("/")
        self._apply_inventory_mode()
        self.comparison.set_stale(False)
        self._set_locations_stale(False)
        self._validated_plan = None
        self._refresh_plan_summary()
        for message in result.parsed.diagnostics:
            self._append_log(message)
        count = len(result.parsed.changes)
        self.status_label.setText(f"Comparison complete: {count} changed object(s).")
        self._append_log(f"STATE comparison-complete changes={count}")
        self._end_bulk_logging()

    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        try:
            if event is not None and event.type() == QEvent.Type.Enter:
                action = watched.property("previewAction") if hasattr(watched, "property") else None
                if action:
                    self._set_hovered_action(str(action))
        except RuntimeError:
            # Qt may already have destroyed the watched widget during shutdown.
            return False
        return super().eventFilter(watched, event)

    def _apply_action_filters(self, actions: object) -> None:
        selected = actions if isinstance(actions, set) else None
        self.comparison.proxy.set_visible_actions(selected)

    def _apply_inventory_mode(self) -> None:
        changed = list(self._last_changed_changes)
        if self._active_profile is None:
            return
        if not self.show_unchanged.isChecked():
            self._inventory_service.cancel()
            self._inventory_token = 0
            self._inventory_pending_key = None
            self.comparison.set_changes(changed)
            return
        key = self._inventory_key(self._active_profile, changed)
        if self._inventory_cache_key == key and self._inventory_cache is not None:
            self.comparison.set_changes(
                changed + list(self._inventory_cache), preserve_expansion=True
            )
            self.progress_label.setText(
                f"Showing {len(self._inventory_cache)} unchanged object(s); "
                "expand folders to view nested objects."
            )
            return
        if self._inventory_pending_key == key and self._inventory_token:
            return
        # Show the compared objects right away. The unchanged objects are
        # merged in when the inventory completes, so the tree never stays
        # empty and no second comparison is needed.
        self.comparison.set_changes(changed)
        self._inventory_pending_key = key
        self.progress_label.setText("Gathering unchanged objects...")
        self._append_log("STATE inventory-started")
        self._inventory_token = self._inventory_service.gather(
            deepcopy(self._active_profile), changed
        )

    @staticmethod
    def _inventory_key(profile: SyncProfile, changed: list[object]) -> object:
        paths = frozenset(
            str(getattr(change, "path", "")).rstrip("/") for change in changed
        )
        return (profile_fingerprint(profile), paths)

    def _inventory_finished(self, token: int, extra: object) -> None:
        if self._closing:
            return
        if token != self._inventory_token:
            return
        self._inventory_token = 0
        changed = list(self._last_changed_changes)
        if (
            not self.show_unchanged.isChecked()
            or self._active_profile is None
        ):
            return
        key = self._inventory_key(self._active_profile, changed)
        if key != self._inventory_pending_key:
            return
        result = list(extra)  # type: ignore[arg-type]
        self._inventory_cache_key = key
        self._inventory_cache = result
        self.comparison.set_changes(
            changed + result, preserve_expansion=True
        )
        self.progress_label.setText(
            f"Inventory complete: {len(result)} unchanged object(s); "
            "expand folders to view nested objects."
        )
        self._append_log(f"STATE inventory-complete unchanged={len(result)}")

    def _inventory_failed(self, token: int, message: str) -> None:
        if self._closing:
            return
        if token != self._inventory_token:
            return
        self._inventory_token = 0
        self._inventory_pending_key = None
        self._append_log(f"Inventory gathering failed: {message}")
        if self.show_unchanged.isChecked():
            self._set_status(
                "Could not gather unchanged objects; showing changed objects only.",
                "warning",
            )
            self.comparison.set_changes(list(self._last_changed_changes))

    def _comparison_error(self, message: str) -> None:
        if self._closing:
            return
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_label.setText("Comparison failed")
        self.status_label.setText("Comparison failed.")
        self._append_log(message)
        self._end_bulk_logging()
        QMessageBox.critical(self, "Comparison failed", message)

    def _log_spec(self, spec: object) -> None:
        argv = getattr(spec, "argv", None)
        if callable(argv):
            argv = argv()
        if argv is None:
            program = getattr(spec, "program", None)
            if program is None:
                return
            argv = [program, *getattr(spec, "arguments", ())]
        self._append_log("$ " + shlex.join([str(item) for item in argv]))

    def _append_log(self, text: str) -> None:
        if not text:
            return
        normalized = text.rstrip("\r\n")
        if not normalized:
            return
        self._log_buffer.append(normalized.replace("\r", "\n"))
        if self._bulk_logging:
            if not self._log_flush_timer.isActive():
                self._log_flush_timer.start()
            return
        self._flush_log()

    def _flush_log(self) -> None:
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        if not self._log_buffer:
            return
        text = "\n".join(self._log_buffer)
        self._log_buffer.clear()
        self.log.appendPlainText(text)
        self._write_session_log(text)

    def _begin_bulk_logging(self) -> None:
        self._bulk_logging = True

    def _end_bulk_logging(self) -> None:
        self._bulk_logging = False
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        self._flush_log()

    @staticmethod
    def _legacy_recent_profile_path() -> Path:
        return Path.home() / ".local" / "share" / "qpy-rsync" / "recent-profile.json"

    def _save_recent_profile(self) -> None:
        try:
            payload = profile_to_json(self._profile())
        except (TypeError, ValueError):
            return
        settings = app_settings()
        settings.setValue("profile/recent", payload)
        settings.remove("profile/recent_path")
        settings.sync()

    def _restore_recent_profile(self) -> bool:
        settings = app_settings()
        payload = str(settings.value("profile/recent", ""))
        if payload:
            try:
                self._apply_profile(profile_from_json(payload))
            except (ValueError, KeyError, TypeError):
                settings.remove("profile/recent")
                settings.sync()
                return False
            return True

        # Migrate the old dedicated recent-profile.json without recreating it.
        stored = str(settings.value("profile/recent_path", "")).strip()
        path = (
            Path(stored).expanduser()
            if stored
            else self._legacy_recent_profile_path()
        )
        if not path.is_file():
            if stored:
                settings.remove("profile/recent_path")
                settings.sync()
            return False
        try:
            profile = load_profile(path)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        settings.setValue("profile/recent", profile_to_json(profile))
        settings.remove("profile/recent_path")
        settings.sync()
        if path == self._legacy_recent_profile_path():
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self._apply_profile(profile)
        except (ValueError, KeyError, TypeError):
            return False
        return True

    def _save_filters(self) -> None:
        settings = app_settings()
        settings.setValue("comparison/filters", encode_filters(self._filters))
        settings.sync()

    def _restore_filters(self) -> None:
        settings = app_settings()
        payload = str(settings.value("comparison/filters", ""))
        try:
            self._filters = decode_filters(payload)
        except (TypeError, ValueError):
            self._filters = []
            self._append_log("Stored filters were invalid and have been ignored.")
        self._update_filter_summary()

    def _save_backup(self) -> None:
        settings = app_settings()
        settings.setValue("comparison/backup", encode_backup(self._backup))
        settings.sync()

    def _restore_backup(self) -> None:
        settings = app_settings()
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
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

    def _update_startup_status(self) -> None:
        if self.source_edit.text().strip() and self.destination_edit.text().strip():
            self._set_status("Ready. Click Compare to refresh the remembered Source and Destination.")
        else:
            self._set_status("Choose Source and Destination above the comparison panes.")

    def _restore_window_state(self) -> None:
        settings = app_settings()
        geometry = decode_binary(settings.value("main-window/geometry"))
        state = decode_binary(settings.value("main-window/state"))
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)
        preview_state = decode_binary(settings.value("command-preview/splitter"))
        if preview_state is not None:
            self.preview_log_splitter.restoreState(preview_state)

    def _shutdown_operations(self) -> None:
        """Stop every running operation before the window is destroyed."""
        for service in (self._service, self._sync_service, self._plan_validation):
            shutdown = getattr(service, "shutdown", None)
            if shutdown is None:
                continue
            try:
                shutdown()
            except RuntimeError:
                pass
        try:
            self._inventory_service.cancel()
        except RuntimeError:
            pass

    def closeEvent(self, event: object) -> None:  # noqa: N802
        # Stop the running rsync processes first. They are owned by the window,
        # so a process that is still running would be destroyed with it.
        self._closing = True
        self._shutdown_operations()
        settings = app_settings()
        settings.setValue(
            "main-window/geometry", encode_binary(self.saveGeometry())
        )
        settings.setValue("main-window/state", encode_binary(self.saveState()))
        settings.setValue(
            "command-preview/splitter",
            encode_binary(self.preview_log_splitter.saveState()),
        )
        settings.sync()
        self.comparison.save_view_state()
        try:
            _current = self._profile()
            _baseline = getattr(self, "_baseline_profile", None)

            def _same_profile(a, b):
                if a is None or b is None:
                    return False
                left = a.to_dict()
                right = b.to_dict()
                left.pop("profile_id", None)
                right.pop("profile_id", None)
                left.pop("name", None)
                right.pop("name", None)
                return left == right

            if _baseline is not None and not _same_profile(_current, _baseline):
                pass
            if (
                os.environ.get("QT_QPA_PLATFORM") != "offscreen"
                and _baseline is not None
                and not _same_profile(_current, _baseline)
            ):
                answer = QMessageBox.question(
                    self,
                    "Save profile",
                    "Settings changed since the last profile load or save. Save current settings as a profile?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    path, _selected = QFileDialog.getSaveFileName(
                        self, "Save Profile", str(Path.home() / "qpy-rsync-profile.json"), "JSON (*.json)"
                    )
                    if path:
                        save_profile(Path(path), self._profile())
                        try:
                            self._baseline_profile = self._profile()
                        except ValueError:
                            self._baseline_profile = None
                        self._append_log(f"Profile saved: {path}")
        except Exception:  # noqa: BLE001
            pass
        self._flush_log()
        self._close_session_log()
        super().closeEvent(event)  # type: ignore[arg-type]
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()  # type: ignore[union-attr]
