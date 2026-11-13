from __future__ import annotations

from copy import deepcopy
import shlex
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QProcess, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPalette,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QToolTip,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.decision_filters import temporary_decision_filter
from qpy_rsync.backend.inventory import (
    InventoryResult,
    gather_destination_metadata,
)
from qpy_rsync.backend.process_runner import ProcessState
from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.core.endpoints import parse_endpoint
from qpy_rsync.storage.profile_store import (
    load_profile,
    profile_from_json,
    profile_to_json,
    save_profile,
)
from qpy_rsync.storage.settings import (
    app_settings,
    decode_binary,
    profiles_directory,
    decode_text,
    encode_binary,
    encode_text,
)


_PAUSE_TOOLTIP = (
    "Pause the running rsync operation.\n"
    "The transfer is suspended and continues with the same button.\n"
    "For a remote endpoint the connection stays open and the transfer\n"
    "resumes where it stopped."
)
_RESUME_TOOLTIP = "Continue the paused rsync operation.\n\nShortcut: F11"

_VERIFY_TOOLTIP = (
    "Verify the selected actions.\n"
    "When no checkbox decisions were changed after the comparison, the\n"
    "latest comparison is reused immediately.\n"
    "Otherwise a second rsync dry run checks the selected subset; that run\n"
    "can be cancelled.\n"
    "For SSH endpoints the dry run connects to the remote host again, so the\n"
    "remote host must be reachable and credentials must be available."
)


def with_shortcut(tooltip: str, shortcut: str) -> str:
    """Add the keyboard shortcut of the matching menu action to a tooltip."""
    if not shortcut:
        return tooltip
    return f"{tooltip}\n\nShortcut: {shortcut}"


def vertical_separator() -> QFrame:
    """A thin line that groups the controls of a row."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(1)
    line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return line


def _inventory_result(payload: object) -> InventoryResult:
    """Read the outcome of an inventory run."""
    if isinstance(payload, InventoryResult):
        return payload
    # Older callers deliver a plain list of unchanged items.
    return InventoryResult(
        unchanged=list(payload),  # type: ignore[call-overload]
        destination_metadata={},
    )
from qpy_rsync.core.enums import EndpointKind, Severity, SyncMode
from qpy_rsync.core.backup_paths import resolve_backup
from qpy_rsync.core.execution_gate import ExecutionGate, ExecutionGateState
from qpy_rsync.core.units import format_size
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
from qpy_rsync.services.sounds import play_completion_sound
from qpy_rsync.services.sync_service import SyncResult, SyncService

from .action_filters import ActionFilterBar
from .command_preview import CommandPreview
from .controls import CONTROL_ICON_SIZE, CONTROL_SIZE
from .flat_comparison_view import FlatComparisonView
from .icons import (
    cancel_icon,
    compare_icon,
    destination_icon,
    filters_icon,
    inventory_mode_icon,
    folder_open_icon,
    log_file_icon,
    open_icon,
    pause_icon,
    save_icon,
    settings_icon,
    source_icon,
    swap_icon,
    synchronize_icon,
    verified_icon,
    verify_icon,
)
from .overview import OverviewPane
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
        self._service.on_log = self._append_rsync_log
        self._service.on_progress = self._comparison_progress
        self._service.on_transient = self._append_transient_log
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
        self._plan_validation.on_log = self._append_rsync_log
        self._plan_validation.on_spec = self._log_spec
        self._plan_validation.on_transient = self._append_transient_log
        self._inventory_service = InventoryService(self)
        self._inventory_service.progress.connect(self._inventory_progress)
        self._inventory_service.finished.connect(self._inventory_finished)
        self._inventory_service.failed.connect(self._inventory_failed)
        # A separate, lighter listing fills in the size and the date of the
        # objects that exist only on the destination.
        self._metadata_service = InventoryService(
            self, gather=gather_destination_metadata
        )
        self._metadata_service.finished.connect(self._metadata_finished)
        self._metadata_token = 0
        self._inventory_token = 0
        self._inventory_pending_key: object | None = None
        self._inventory_cache_key: object | None = None
        self._inventory_cache: list[object] | None = None
        self._dialog_filter_context: object | None = None
        self._diff_staging_directories: list[Path] = []
        self._last_backup_message: tuple[str, str] | None = None
        self._last_changed_changes: list[object] = []
        self._sync_service = SyncService(self)
        self._sync_service.on_started = self._sync_started
        self._sync_service.on_finished = self._sync_finished
        self._sync_service.on_error = self._sync_error
        self._sync_service.on_stdout = self._append_rsync_log
        self._sync_service.on_stderr = self._append_rsync_log
        self._sync_service.on_progress = self._sync_progress
        self._sync_service.on_spec = self._log_spec
        self._sync_service.on_transient = self._append_transient_log
        self._last_plan_summary: str | None = None
        self._filters: list[FilterRule] = []
        self._sound_enabled = True
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
        self._sound_enabled = app_settings().value(
            "sound/enabled", True, type=bool
        )
        self._update_startup_status()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

    def _build_backup_panel(self) -> None:
        """Build the backup settings shown in the Settings dialog."""
        self._backup_panel = QWidget(self._config_holder)
        layout = QFormLayout(self._backup_panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addRow("Backup directory", self.backup_edit)
        layout.addRow("", self.backup_browse)
        layout.addRow("", self.protect_backup)
        note = QLabel(
            "An empty directory disables backups. The toolbar button opens the "
            "configured directory."
        )
        note.setWordWrap(True)
        layout.addRow("", note)
        self._backup_panel.setVisible(False)

    def _build_log_panel(self) -> None:
        """Build the logging settings shown in the Settings dialog."""
        self._log_panel = QWidget(self._config_holder)
        layout = QFormLayout(self._log_panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addRow("", self.log_file_checkbox)
        layout.addRow("Log file", self.log_file_edit)
        layout.addRow("", self.log_file_browse)
        note = QLabel(
            "The journal is written to this file. The toolbar button opens it."
        )
        note.setWordWrap(True)
        layout.addRow("", note)
        self._log_panel.setVisible(False)

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

        self.comparison = FlatComparisonView()
        self.comparison.diff_requested.connect(self._open_diff_tool)
        self.comparison.decision_changed.connect(self._invalidate_validated_plan)
        self.comparison.changes_updated.connect(self._overview_updated)
        self.comparison.sort_changed.connect(self._comparison_sorted)

        if hasattr(self.comparison, "filter_requested"):
            self.comparison.filter_requested.connect(self._add_filter_phrase)
        self.comparison.controls.setParent(root)

        controls = QHBoxLayout()
        self.sync_mode = QComboBox()
        self.sync_mode.addItem("Update", SyncMode.UPDATE)
        self.sync_mode.addItem("Mirror", SyncMode.MIRROR)
        self.sync_mode.addItem("New Only", SyncMode.NEW_ONLY)
        self.sync_mode.setToolTip(
            "Mode selection\n"
            "Update: copy new and changed items; keep destination-only items.\n"
            "Mirror: make Destination match Source, including deletions.\n"
            "New Only: copy missing items; do not update or delete existing items."
        )
        controls.addWidget(self.sync_mode)
        self.swap_button = QToolButton()
        self.swap_button.setIcon(swap_icon())
        self.swap_button.setToolTip("Swap Source and Destination")
        self.swap_button.setAccessibleName("Swap Source and Destination")
        controls.addWidget(self.swap_button)
        controls.addWidget(vertical_separator())
        self.compare_button = QToolButton()
        self.compare_button.setIcon(compare_icon())
        self.compare_button.setToolTip(
            "Compare Source and Destination using an rsync dry run.\n"
            "No files are changed.\n"
            "For SSH endpoints this connects to the remote host, so the remote "
            "host must be reachable and credentials must be available."
        )
        self.compare_button.setAccessibleName("Compare")
        self.cancel_button = QToolButton()
        self.cancel_button.setIcon(cancel_icon())
        self.cancel_button.setToolTip("Cancel the running operation")
        self.cancel_button.setAccessibleName("Cancel the running operation")
        self.cancel_button.setEnabled(False)
        self.pause_button = QToolButton()
        self.pause_button.setIcon(pause_icon())
        self.pause_button.setEnabled(False)
        self.pause_button.setCheckable(True)
        self.pause_button.setToolTip(_PAUSE_TOOLTIP)
        self.pause_button.setAccessibleName("Pause the running operation")
        self.inventory_after_compare_button = QToolButton()
        self.inventory_after_compare_button.setIcon(inventory_mode_icon())
        self.inventory_after_compare_button.setCheckable(True)
        self.inventory_after_compare_button.setToolTip(
            "Run an inventory after every comparison.\n"
            "The inventory lists Source and Destination and adds the unchanged\n"
            "items to the comparison, so they are shown together with the\n"
            "changed ones. The unchanged button then reuses this result\n"
            "instead of running the inventory a second time."
        )
        self.inventory_after_compare_button.setAccessibleName(
            "Inventory after comparison"
        )
        self.validate_plan_button = QToolButton()
        self.validate_plan_button.setIcon(verify_icon())
        self.validate_plan_button.setToolTip(_VERIFY_TOOLTIP)
        self.validate_plan_button.setAccessibleName("Verify Actions")
        self.synchronize_button = QToolButton()
        self.synchronize_button.setIcon(synchronize_icon())
        self.synchronize_button.setAccessibleName("Synchronize")
        self.synchronize_button.setToolTip(
            "Open the confirmation dialog and write the verified plan.\n"
            "The button stays disabled until Verify Actions (F8) succeeds for\n"
            "the current selection; changed filters or decisions invalidate\n"
            "the verification."
        )
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(False)
        self.filters_button = QToolButton()
        self.filters_button.setIcon(filters_icon())
        self.filters_button.setToolTip("Edit the persistent filter rules")
        self.filters_button.setAccessibleName("Filters")
        self.load_profile_button = QToolButton()
        self.load_profile_button.setIcon(open_icon())
        self.load_profile_button.setToolTip("Load Profile...")
        self.load_profile_button.setAccessibleName("Load Profile")
        self.save_profile_button = QToolButton()
        self.save_profile_button.setIcon(save_icon())
        self.save_profile_button.setToolTip("Save Profile...")
        self.save_profile_button.setAccessibleName("Save Profile")
        self.backup_open = self._external_open_button(
            "backup-open-button",
            folder_open_icon(),
            "Open the backup directory",
            self._open_backup_directory,
        )
        self.log_file_open = self._external_open_button(
            "log-open-button",
            log_file_icon(),
            "Open the log file",
            self._open_log_file,
        )
        for button, section in (
            (self.backup_open, "backup"),
            (self.log_file_open, "logging"),
        ):
            self._configure_open_button_menu(button, section)
        self.settings_button = QToolButton()
        self.settings_button.setIcon(settings_icon())
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self._edit_settings)

        for button in (
            self.swap_button,
            self.compare_button,
            self.inventory_after_compare_button,
            self.validate_plan_button,
            self.synchronize_button,
            self.cancel_button,
            self.pause_button,
            self.filters_button,
            self.load_profile_button,
            self.save_profile_button,
            self.backup_open,
            self.log_file_open,
            self.settings_button,
        ):
            button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
            button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.show_unchanged = self.comparison.inventory_button
        self.show_unchanged.toggled.connect(lambda _checked: self._apply_inventory_mode())
        self.inventory_after_compare_button.toggled.connect(
            self._inventory_after_compare_changed
        )
        controls.addWidget(self.compare_button)
        controls.addWidget(self.inventory_after_compare_button)
        for widget in (
            self.validate_plan_button,
            self.synchronize_button,
            self.cancel_button,
            self.pause_button,
            self.filters_button,
            self.load_profile_button,
            self.save_profile_button,
            self.backup_open,
            self.log_file_open,
            self.settings_button,
        ):
            controls.addWidget(widget)
        controls.addWidget(vertical_separator())
        controls.addWidget(self.comparison.controls, 1)
        layout.addLayout(controls)
        self._controls_layout = controls

        locations = QHBoxLayout()
        source_panel = self._location_panel("Source", self.source_edit, trailing=True)
        self.action_filters = ActionFilterBar(self)
        self.action_filters.changed.connect(self._apply_action_filters)
        self.action_filters.hidden_toggled.connect(self._apply_show_hidden)
        destination_panel = self._location_panel("Destination", self.destination_edit)
        locations.addWidget(source_panel, 40)
        locations.addWidget(self.action_filters, 0, Qt.AlignmentFlag.AlignVCenter)
        locations.addWidget(vertical_separator())
        locations.addWidget(self.comparison.view_controls, 0, Qt.AlignmentFlag.AlignVCenter)
        locations.addWidget(vertical_separator())
        locations.addWidget(destination_panel, 40)
        layout.addLayout(locations)
        self._locations_layout = locations

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter = splitter
        splitter.addWidget(self.comparison)
        log_panel = QWidget(self)
        log_layout = QHBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_splitter = QSplitter(Qt.Orientation.Horizontal)
        log_splitter.setChildrenCollapsible(False)
        log_splitter.setHandleWidth(6)
        log_column = QWidget(self)
        log_layout_column = QVBoxLayout(log_column)
        log_layout_column.setContentsMargins(0, 0, 0, 0)
        log_layout_column.setSpacing(2)
        self.log_header = QLabel("Journal")
        self.log_header.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.state_label = QLabel("State:")
        self.state_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        # The state is shown in a read-only field that uses the background of
        # the window, so it does not look like another black text box.
        self.status_edit = QLineEdit()
        self.status_edit.setReadOnly(True)
        self.status_edit.setFrame(False)
        self.status_edit.setCursorPosition(0)
        self.status_edit.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.status_edit.setObjectName("status-edit")
        self._apply_status_style("")
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
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setVisible(False)
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
        header_row.addStretch(1)
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
        log_layout_column.addWidget(self.progress_bar)
        log_layout_column.addWidget(self.progress_label)
        log_layout_column.addWidget(self.preview_log_splitter, 1)
        log_splitter.addWidget(log_column)
        # The overview summarises the comparison next to the journal.
        self.overview = OverviewPane(self)
        self.overview.folder_activated.connect(self._overview_folder_activated)
        self.overview.hide_requested.connect(self._hide_path)
        self.overview.show_requested.connect(self._show_path)
        self.overview.filter_requested.connect(self._add_filter_phrase)
        log_splitter.addWidget(self.overview)
        log_splitter.setStretchFactor(0, 1)
        log_splitter.setStretchFactor(1, 0)
        log_splitter.setSizes([600, 500])
        log_layout.addWidget(log_splitter, 1)
        splitter.addWidget(log_panel)
        splitter.setSizes([380, 250])
        layout.addWidget(splitter, 1)

        # The logging and backup settings are shown in the Settings dialog.
        # The widgets live here so their state and signals stay with the
        # window; the dialog only reparents them while it is open.
        self._config_holder = QWidget(self)
        self._config_holder.setVisible(False)

        self.backup_edit = QLineEdit()
        self.backup_edit.setPlaceholderText("Empty disables backups")
        self.backup_browse = QPushButton("Browse...")
        self.protect_backup = QCheckBox("Protect nested backups")
        self.protect_backup.setChecked(True)
        self._build_backup_panel()

        self.log_file_checkbox = QCheckBox("Enable logging")
        self.log_file_checkbox.setChecked(True)
        self.log_file_edit = QLineEdit(str(self._log_file_path))
        self.log_file_browse = QPushButton("Browse...")
        self._build_log_panel()

        self.setCentralWidget(root)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.state_label)
        self.statusBar().addWidget(self.status_edit, 1)
        self._build_menus()
        self._build_menu_button()

        self.compare_button.clicked.connect(self._compare)
        self.sync_mode.currentIndexChanged.connect(self._sync_mode_changed)
        self.cancel_button.clicked.connect(self._cancel_active_operation)
        self.pause_button.clicked.connect(self._toggle_pause)
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
        for button, shortcut in (
            (self.compare_button, "F5"),
            (self.validate_plan_button, "F8"),
            (self.synchronize_button, "F9"),
            (self.cancel_button, "F10"),
            (self.pause_button, "F11"),
            (self.filters_button, "F7"),
            (self.save_profile_button, "F2"),
            (self.load_profile_button, "F3"),
        ):
            button.setToolTip(with_shortcut(button.toolTip(), shortcut))
        self.show_unchanged.setToolTip(with_shortcut(self.show_unchanged.toolTip(), "F6"))
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
        self.backup_edit.textChanged.connect(self._update_external_open_states)
        self.log_file_edit.textChanged.connect(self._update_external_open_states)
        self._update_external_open_states()

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

    def _build_menus(self) -> None:
        """Create the application menu with its shortcuts."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        self._add_action(
            file_menu, "Load Profile...", "F3", self._load_profile
        )
        self._add_action(
            file_menu, "Save Profile...", "F2", self._save_profile
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit", "Ctrl+Q", self.close)

        edit_menu = menu_bar.addMenu("&Edit")
        self._add_action(
            edit_menu, "Filter/Find", "Ctrl+F", self.comparison.focus_path_filter
        )
        self._add_action(edit_menu, "Settings", "Ctrl+,", self._edit_settings)

        actions_menu = menu_bar.addMenu("&Actions")
        self._add_action(
            actions_menu,
            "Reset All Decisions",
            "Ctrl+Z",
            self.comparison.reset_all_decisions,
        )
        self._add_action(
            actions_menu, "Method", "F4", lambda: self.sync_mode.setFocus()
        )
        actions_menu.addSeparator()
        self._add_action(actions_menu, "Compare", "F5", self._compare)
        self._add_action(actions_menu, "Inventory", "F6", self._toggle_inventory)
        self._add_action(actions_menu, "Filters", "F7", self._edit_filters)
        self._add_action(
            actions_menu, "Validate Actions", "F8", self._validate_selected_plan
        )
        self._add_action(
            actions_menu, "Synchronize", "F9", self._show_sync_confirmation
        )
        self._add_action(
            actions_menu, "Cancel", "F10", self._cancel_active_operation
        )
        self._add_action(actions_menu, "Pause", "F11", self._toggle_pause)

        help_menu = menu_bar.addMenu("&Help")
        self._add_action(help_menu, "How-To", "F1", self._show_how_to)
        self._add_action(help_menu, "About qpy-rsync", "", self._show_about)

    def _add_action(self, menu: object, text: str, shortcut: str, slot: object) -> object:
        from PySide6.QtGui import QAction, QKeySequence

        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)  # type: ignore[arg-type]
        menu.addAction(action)  # type: ignore[attr-defined]
        return action

    def _build_menu_button(self) -> None:
        """Mirror the menu bar in a button, for desktops without a global menu."""
        menu = QMenu(self)
        for menu_action in self.menuBar().actions():
            submenu = menu_action.menu()
            if submenu is None:
                continue
            mirror = menu.addMenu(submenu.title().replace("&", ""))
            for item in submenu.actions():
                if item.isSeparator():
                    mirror.addSeparator()
                else:
                    mirror.addAction(item)
        self.comparison.menu_button.setMenu(menu)

    def _show_how_to(self) -> None:
        from .help_dialog import show_how_to

        show_how_to(self)

    def _show_about(self) -> None:
        from .about import show_about

        show_about(self)

    def _toggle_inventory(self) -> None:
        """Show or hide the unchanged items."""
        self.show_unchanged.setChecked(not self.show_unchanged.isChecked())

    def _external_open_button(
        self, name: str, icon: object, tooltip: str, slot: object
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName(name)
        button.setIcon(icon)  # type: ignore[arg-type]
        button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(slot)  # type: ignore[arg-type]
        return button

    def _update_external_open_states(self) -> None:
        for edit, button in (
            (self.source_edit, getattr(self, "source_open_button", None)),
            (self.destination_edit, getattr(self, "destination_open_button", None)),
        ):
            if button is None:
                continue
            try:
                endpoint = parse_endpoint(edit.text())
                button.setEnabled(endpoint.kind is EndpointKind.LOCAL)
            except ValueError:
                button.setEnabled(False)
        backup = getattr(self, "backup_open", None)
        if backup is not None:
            try:
                destination = parse_endpoint(self.destination_edit.text())
                local = destination.kind is EndpointKind.LOCAL
            except ValueError:
                local = False
            backup.setEnabled(local and bool(self.backup_edit.text().strip()))
        log_button = getattr(self, "log_file_open", None)
        if log_button is not None:
            log_button.setEnabled(bool(self.log_file_edit.text().strip()))

    def _open_path(self, path: Path, what: str) -> None:
        if not path.exists():
            message = f"{what} does not exist:\n{path}"
            self._set_status(f"{what} does not exist: {path}", "warning")
            QMessageBox.warning(self, "Location not found", message)
            return
        url = QUrl.fromLocalFile(str(path))
        if QDesktopServices.openUrl(url):
            self._append_log(f"Opened {what}: {path}")
            return
        started, _pid = QProcess.startDetached("xdg-open", [str(path)])
        if started:
            self._append_log(f"Opened {what}: {path}")
            return
        message = f"Could not open {what}:\n{path}"
        self._set_status(message, "error")
        QMessageBox.critical(self, "Could not open", message)

    def _open_location_directory(self, title: str) -> None:
        edit = self.source_edit if title == "Source" else self.destination_edit
        try:
            endpoint = parse_endpoint(edit.text())
        except ValueError as exc:
            self._set_status(str(exc), "error")
            return
        if endpoint.kind is not EndpointKind.LOCAL:
            self._set_status(
                f"The {title} directory is remote and cannot be opened locally.",
                "warning",
            )
            return
        self._open_path(Path(endpoint.path).expanduser(), f"{title} directory")

    def _open_backup_directory(self) -> None:
        if not self.backup_edit.text().strip():
            self._set_status("No backup directory is configured.", "warning")
            return
        try:
            profile = self._profile()
        except ValueError as exc:
            self._set_status(str(exc), "error")
            return
        if profile.destination.kind is not EndpointKind.LOCAL:
            self._set_status(
                "The backup directory is on a remote Destination and cannot "
                "be opened locally.",
                "warning",
            )
            return
        resolved = resolve_backup(profile)
        if resolved is None:
            self._set_status("No backup directory is configured.", "warning")
            return
        self._open_path(
            Path(resolved.directory).expanduser(), "backup directory"
        )

    def _open_log_file(self) -> None:
        text = self.log_file_edit.text().strip()
        path = (Path(text).expanduser() if text else self._log_file_path)
        if not path.exists():
            message = f"Log file does not exist:\n{path}"
            self._set_status(message, "warning")
            QMessageBox.warning(self, "Log file not found", message)
            return
        self._open_path(path, "log file")

    @staticmethod
    def _missing_local_directories(profile: SyncProfile) -> list[str]:
        missing: list[str] = []
        for title, endpoint in (
            ("Source", profile.source),
            ("Destination", profile.destination),
        ):
            if endpoint.kind is not EndpointKind.LOCAL:
                continue
            path = Path(endpoint.path).expanduser()
            if not path.exists():
                missing.append(f"{title}: {path} does not exist.")
            elif not path.is_dir():
                missing.append(f"{title}: {path} is not a directory.")
        return missing

    def _warn_missing_local_directories(
        self, missing: list[str], action: str
    ) -> None:
        detail = "\n".join(missing)
        self._set_status(f"{action} cancelled: {detail}", "warning")
        QMessageBox.warning(
            self,
            "Location not found",
            detail + "\n\nCreate the directory or choose another location.",
        )

    def _location_panel(
        self, title: str, edit: QLineEdit, *, trailing: bool = False
    ) -> QWidget:
        panel = QWidget(self)
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        icon = QLabel()
        icon.setPixmap(
            (source_icon() if title == "Source" else destination_icon()).pixmap(
                CONTROL_SIZE, CONTROL_SIZE
            )
        )
        # The glyph matches the size of the buttons in the same row.
        icon.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName(f"{title.lower()}-location-label")
        icon.setToolTip(f"{title} directory")
        icon.setAccessibleName(f"{title} directory")
        row.addWidget(icon)
        open_button = self._external_open_button(
            f"{title.lower()}-open-button",
            folder_open_icon(),
            f"Open the {title} directory",
            lambda: self._open_location_directory(title),
        )
        if title == "Source":
            self.source_open_button = open_button
        else:
            self.destination_open_button = open_button
        row.addWidget(open_button)
        browse = QPushButton("Browse...")
        browse.setToolTip(f"Select the {title} directory")
        browse.clicked.connect(lambda: self._browse(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        if trailing:
            row.addWidget(vertical_separator())
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
        self._update_external_open_states()

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
        self._update_external_open_states()
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

    def _apply_status_style(self, color: str) -> None:
        style = "background-color: palette(window); border: none; padding: 0px 2px;"
        if color:
            style += f" color: {color};"
        self.status_edit.setStyleSheet(style)

    def _play_completion_sound(self, kind: str) -> None:
        """Play the completion sound when the user asked for it."""
        if not getattr(self, "_sound_enabled", False):
            return
        try:
            play_completion_sound(kind)
        except Exception:  # noqa: BLE001 - a sound must never break the sync
            pass

    def _set_state(self, text: str, severity: str = "info") -> None:
        """Update the current operation state shown in the status bar."""
        severity = severity.lower()
        colors = {"warning": "#0891B2", "error": "#B91C1C", "success": "#15803D"}
        self.status_edit.setToolTip(text)
        self._apply_status_style(colors.get(severity, ""))
        self.status_edit.setText(text.replace("\n", " "))

    def _set_status(self, text: str, severity: str = "info") -> None:
        """Write a message to the journal; warnings do not replace the state."""
        severity = severity.lower()
        journal_text = text
        for prefix in ("Warning: ", "Error: "):
            if journal_text.startswith(prefix):
                journal_text = journal_text[len(prefix):]
                break
        self._append_log(journal_text, severity=severity)

    def _set_backup_message(self, text: str, severity: str = "info") -> None:
        if severity == "info" and text.startswith("Backups are disabled"):
            return
        shortened = text.replace("Backups are disabled.", "").strip()
        if not shortened:
            return
        key = (shortened, severity)
        if key == self._last_backup_message:
            return
        self._last_backup_message = key
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
            backup=BackupOptions(
                directory=self.backup_edit.text().strip(),
                protect_nested=self.protect_backup.isChecked(),
            ),
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
                "Mirror can delete items that exist only in Destination. Click Compare and review deletions.",
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
        self._set_state(
            "Stale comparison: filter rules changed. Compare again to refresh results.",
            "warning",
        )

    def _configure_open_button_menu(self, button: QToolButton, section: str) -> None:
        """Give an open button a right-click menu that leads to its settings."""
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda point, b=button, s=section: self._open_button_menu(b, point, s)
        )

    def _open_button_menu(self, button: QToolButton, point: object, section: str) -> None:
        menu = QMenu(button)
        open_action = menu.addAction(button.toolTip())
        configure = menu.addAction("Configure...")
        selected = menu.exec(button.mapToGlobal(point))
        if selected is open_action:
            button.click()
        elif selected is configure:
            self._edit_settings(section)

    def _edit_settings(self, section: str = "general") -> None:
        """Open the settings dialog on the given section."""
        from .settings_dialog import SettingsDialog

        if isinstance(section, bool):
            section = "general"
        dialog = SettingsDialog(
            self,
            holder=self._config_holder,
            log_panel=self._log_panel,
            backup_panel=self._backup_panel,
            sound_enabled=self._sound_enabled,
            section=str(section),
        )
        # Apply the log and backup fields the dialog may have changed.
        accepted = dialog.exec()
        if accepted:
            self._logging_settings_changed()
            self._backup_changed()
            enabled = dialog.sound_enabled()
            if enabled != self._sound_enabled:
                self._sound_enabled = enabled
                settings = app_settings()
                settings.setValue("sound/enabled", enabled)
                settings.sync()
        # The panels return to their holder in any case.
        self._update_external_open_states()

    def _add_filter_phrase(self, label: str, path: object) -> None:
        """Add an rsync exclude rule produced by the context menu."""
        from qpy_rsync.core.enums import FilterRuleType
        from qpy_rsync.core.models import FilterRule

        if not isinstance(path, str):
            return
        pattern = label.strip()
        if not pattern:
            return
        rule = FilterRule(
            pattern,
            rule_type=FilterRuleType.EXCLUDE,
            comment=f"Added from {path}",
        )
        if any(
            item.rule == rule.rule and item.rule_type is rule.rule_type
            for item in self._filters
        ):
            self._append_log(f"Filter already present: {pattern}", severity="warning")
            return
        self._filters.append(rule)
        self._save_filters()
        self._update_filter_summary(stale=True)
        self.comparison.set_stale(True)
        self._invalidate_plan_context()
        self._set_state(
            f"Stale comparison: added the filter {pattern}. "
            "Compare again to refresh the results.",
            "warning",
        )
        self._append_log(f"Added rsync filter: {pattern}", severity="info")

    def _save_profile(self) -> None:
        default_path = profiles_directory() / "qpy-rsync-profile.json"
        path, _selected = QFileDialog.getSaveFileName(
            self, "Save Profile", str(default_path), "JSON (*.json)"
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
            self, "Load Profile", str(profiles_directory()), "JSON (*.json)"
        )
        if not path:
            return
        profile = load_profile(Path(path))
        self._apply_profile(profile)
        self._save_recent_profile()
        self._baseline_profile = self._profile()
        self._append_log(f"Profile loaded: {path}")

    def _apply_profile(self, profile: SyncProfile) -> None:
        self.source_edit.setText(
            profile.source.rsync_operand()
            if profile.source.kind is EndpointKind.SSH
            else profile.source.path
        )
        self.destination_edit.setText(
            profile.destination.rsync_operand()
            if profile.destination.kind is EndpointKind.SSH
            else profile.destination.path
        )
        index = self.sync_mode.findData(profile.transfer.sync_mode)
        if index >= 0:
            self.sync_mode.setCurrentIndex(index)
        self.backup_edit.setText(profile.backup.directory)
        self.protect_backup.setChecked(profile.backup.protect_nested)
        self._backup = BackupOptions(
            directory=profile.backup.directory,
            protect_nested=profile.backup.protect_nested,
        )
        self._filters = list(profile.filters)
        self._save_filters()
        self._update_filter_summary(stale=False)
        self._update_backup_status()
        self._update_external_open_states()
        self._update_command_preview()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

    def _update_filter_summary(self, *, stale: bool = False) -> None:
        enabled = sum(1 for item in self._filters if item.enabled)
        total = len(self._filters)
        self.filters_button.setAccessibleName(f"Filters [{enabled}/{total}]")
        self.filters_button.setIcon(
            filters_icon(active=enabled > 0, stale=stale)
        )
        tooltip = (
            f"Filters [{enabled}/{total}]\n"
            f"{enabled} of {total} persistent filter rules are enabled.\n"
            "The first matching rsync rule wins."
        )
        if stale:
            tooltip += (
                "\n\nSTALE: the comparison is out of date because filter rules changed. "
                "Compare again to refresh results."
            )
        self.filters_button.setToolTip(with_shortcut(tooltip, "F7"))

    def _backup_changed(self) -> None:
        updated = BackupOptions(
            directory=self.backup_edit.text().strip(),
            protect_nested=self.protect_backup.isChecked(),
        )
        if updated == self._backup:
            self._update_backup_status()
            return
        self._backup = updated
        self._update_external_open_states()
        self._save_recent_profile()
        self._update_backup_status()
        self._validated_plan = None
        self._set_verify_state("idle")
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
            return build_compare_spec(profile, filter_file=Path("<temporary decision filter>"))
        if action == "synchronize":
            effective = deepcopy(profile)
            effective.transfer.delete = any(
                item.included and item.action is ChangeAction.DELETE
                for item in (self._current_plan.items if self._current_plan else ())
            )
            return build_sync_spec(effective, filter_file=Path("<temporary decision filter>"))
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

    def _set_verify_state(self, state: str) -> None:
        """Update the icon and the accessible label of Verify Actions."""
        if state == "verified":
            self.validate_plan_button.setIcon(verified_icon())
            self.validate_plan_button.setAccessibleName("Actions Verified")
            self.validate_plan_button.setToolTip(
                with_shortcut(
                    "Actions verified. Verify again to refresh the plan.", "F8"
                )
            )
        elif state == "verifying":
            self.validate_plan_button.setIcon(verify_icon())
            self.validate_plan_button.setAccessibleName("Verifying selected actions")
            self.validate_plan_button.setToolTip("Verifying selected actions...")
        else:
            self.validate_plan_button.setIcon(verify_icon())
            self.validate_plan_button.setAccessibleName("Verify Actions")
            self.validate_plan_button.setToolTip(with_shortcut(_VERIFY_TOOLTIP, "F8"))

    def _invalidate_plan_context(self) -> None:
        self._execution_gate.invalidate()
        self.synchronize_button.setEnabled(False)
        self._current_plan = None
        self._validated_plan = None
        self._last_plan_summary = None
        self.validate_plan_button.setEnabled(False)
        self._set_verify_state("idle")

    def _invalidate_validated_plan(self) -> None:
        self._validated_plan = None
        self.synchronize_button.setEnabled(False)
        self._set_verify_state("idle")
        if self._active_profile is not None and self.comparison.model.changes:
            self._refresh_plan_summary()

    def _refresh_plan_summary(self) -> None:
        if self._active_profile is None:
            self._current_plan = None
            self._last_plan_summary = None
            self.overview.set_statistics(None)
            self.validate_plan_button.setEnabled(False)
            return
        self._update_hidden_count()
        self._current_plan = build_execution_plan(
            self._active_profile,
            self.comparison.model.changes,
            self.comparison.model.decisions,
            getattr(self.comparison.model, "hidden", None),
        )
        summary = self._current_plan.summary
        noun = "item" if summary.included == 1 else "items"
        text = (
            f"Selected: {summary.included} {noun}, "
            f"{format_size(summary.total_size)}; "
            f"new {summary.creates}, updated {summary.updates}, "
            f"metadata {summary.metadata}, replaced {summary.replacements}, "
            f"deleted {summary.deletions}; "
            f"kept {summary.retained_destination_only}, unchecked {summary.excluded}, "
            f"modified {summary.modified}, destructive {summary.destructive}; "
            f"backup {'on' if summary.backup_enabled else 'off'}"
        )
        if text != self._last_plan_summary:
            self._last_plan_summary = text
            self._append_log(text)
        self.overview.set_statistics(summary)
        self.validate_plan_button.setEnabled(summary.included > 0)
        self.synchronize_button.setEnabled(False)
        self._execution_gate.selection_changed(included=summary.included)

    def _validate_selected_plan(self) -> None:
        self._backup_changed()
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
        self._set_verify_state("verifying")
        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self._reset_pause_button()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Verifying selected actions...")
        self._set_state("Verifying selected actions...")
        self._append_log("STATE verifying-selected-actions")

    def _plan_validation_finished(self, result: PlanValidationResult) -> None:
        if self._closing:
            return
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self.validate_plan_button.setEnabled(True)
        self._set_verify_state("idle")
        if result.valid:
            self._validated_plan = self._current_plan
            self._execution_gate.verification_succeeded()
            self.synchronize_button.setEnabled(True)
            self._set_verify_state("verified")
            if self._current_plan is not None:
                summary = self._current_plan.summary
                noun = "item" if summary.included == 1 else "items"
                self._append_log(
                    "Actions verified, selected: "
                    f"new {summary.creates}, updated {summary.updates}, "
                    f"metadata {summary.metadata}, replaced {summary.replacements}, "
                    f"deleted {summary.deletions}; "
                    f"{summary.included} {noun}, {format_size(summary.total_size)}"
                )
            self.progress_bar.setValue(100)
            self.progress_label.setText("Selected actions verified")
            self._set_state("Selected actions verified.", "success")
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
        self.progress_label.setText("Plan validation failed")
        self._end_bulk_logging()
        QMessageBox.critical(self, "Plan validation mismatch", detail or "Validation result differed from the selected plan.")
        self._set_state(
            "Plan validation failed; synchronization remains blocked.", "error"
        )

    def _plan_validation_cancelled(self) -> None:
        if self._closing:
            return
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self._validated_plan = None
        if self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._execution_gate.verification_failed()
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(self._current_plan is not None)
        self._set_verify_state("idle")
        self.progress_label.setText("Action verification cancelled")
        self._set_state("Action verification was cancelled.", "warning")
        self._append_log("STATE verification-cancelled")
        self._end_bulk_logging()

    def _plan_validation_error(self, message: str) -> None:
        self.cancel_button.setEnabled(False)
        self._validated_plan = None
        if self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._execution_gate.verification_failed()
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(self._current_plan is not None)
        self._set_verify_state("idle")
        self.progress_label.setText("Plan validation failed")
        self._set_state("Plan validation failed.", "error")
        self._append_log(message, severity="error")
        self._end_bulk_logging()
        QMessageBox.critical(self, "Plan validation failed", message)

    def _show_sync_confirmation(self) -> None:
        self._backup_changed()
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
        self._cleanup_dialog_filter()
        filter_context = temporary_decision_filter(self._validated_plan)
        filter_path = filter_context.__enter__()
        self._dialog_filter_context = filter_context
        started = False
        try:
            dialog = SyncConfirmationDialog(
                self._active_profile,
                self._validated_plan,
                self,
                filter_path=filter_path,
            )
            accepted = bool(dialog.exec())
            if not accepted:
                self._execution_gate.confirmation_cancelled()
                self.synchronize_button.setEnabled(True)
                return
            try:
                self._sync_service.synchronize(
                    self._active_profile,
                    self._validated_plan,
                    filter_path=filter_path,
                )
                started = True
            except ValueError as exc:
                self._execution_gate.confirmation_cancelled()
                self.synchronize_button.setEnabled(True)
                QMessageBox.critical(self, "Synchronization blocked", str(exc))
        finally:
            if not started:
                self._cleanup_dialog_filter()

    def _cleanup_dialog_filter(self) -> None:
        context = self._dialog_filter_context
        self._dialog_filter_context = None
        if context is not None:
            context.__exit__(None, None, None)  # type: ignore[attr-defined]

    def _cancel_active_operation(self) -> None:
        if self._execution_gate.state is ExecutionGateState.EXECUTING:
            self._sync_service.cancel()
        elif self._execution_gate.state is ExecutionGateState.VERIFYING:
            self._plan_validation.cancel()
        else:
            self._service.cancel()

    def _running_service(self) -> object | None:
        """Return the service of the operation that is currently running."""
        if self._execution_gate.state is ExecutionGateState.EXECUTING:
            return self._sync_service
        if self._execution_gate.state is ExecutionGateState.VERIFYING:
            return self._plan_validation
        if self._service.state is ProcessState.RUNNING:
            return self._service
        return None

    def _reset_pause_button(self) -> None:
        self.pause_button.setChecked(False)
        self.pause_button.setText("Pause")
        self.pause_button.setToolTip(_PAUSE_TOOLTIP)

    def _toggle_pause(self) -> None:
        """Suspend or continue the running rsync operation."""
        service = self._running_service()
        if service is None:
            self.pause_button.setChecked(False)
            return
        if self.pause_button.isChecked():
            if not service.pause():  # type: ignore[attr-defined]
                self.pause_button.setChecked(False)
                self._set_status("The operation could not be paused.", "warning")
                return
            self.pause_button.setText("Resume")
            self.pause_button.setToolTip(_RESUME_TOOLTIP)
            self.progress_label.setText("Paused")
            self._set_status(
                "The rsync operation is paused. Continue it with the Pause button.",
                "warning",
            )
            self._append_log("STATE operation-paused")
            return
        if not service.resume():  # type: ignore[attr-defined]
            self._set_status("The operation could not be continued.", "warning")
            return
        self.pause_button.setText("Pause")
        self.pause_button.setToolTip(_PAUSE_TOOLTIP)
        self.progress_label.setText("Continuing...")
        self._set_status("The rsync operation continues.", "info")
        self._append_log("STATE operation-resumed")

    def _set_busy_controls(self, busy: bool) -> None:
        self.compare_button.setEnabled(not busy)
        self.validate_plan_button.setEnabled(False if busy else self._current_plan is not None)
        self.synchronize_button.setEnabled(False)
        self.swap_button.setEnabled(not busy)
        self.filters_button.setEnabled(not busy)
        self.inventory_after_compare_button.setEnabled(not busy)
        self.sync_mode.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        self.destination_edit.setEnabled(not busy)
        self.backup_edit.setEnabled(not busy)
        self.backup_browse.setEnabled(not busy and self.backup_browse.isEnabled())
        self.protect_backup.setEnabled(not busy and self.protect_backup.isEnabled())
        self.cancel_button.setEnabled(busy)
        self.pause_button.setEnabled(busy)
        if not busy:
            self._reset_pause_button()

    def _sync_started(self) -> None:
        self._begin_bulk_logging()
        self._set_hovered_action("synchronize")
        self._execution_gate.execution_started()
        self._set_busy_controls(True)
        self.comparison.set_stale(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Synchronizing...")
        self._set_state("Synchronizing...")
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
            f"Synchronizing... {int(percent)}% ({completed} items transferred, "
            f"{remaining} remaining)"
        )

    def _sync_finished(self, result: SyncResult) -> None:
        self._cleanup_dialog_filter()
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
        self._last_plan_summary = None
        self._set_state("Synchronization complete", "success")
        self._play_completion_sound(
            "success" if result.exit_code == 0 else "error"
        )
        self._set_status(
            f"Synchronization completed with rsync status {result.exit_code}. Refreshing comparison...",
            "success",
        )
        QTimer.singleShot(0, self._compare)

    def _sync_error(self, message: str, cancelled: bool = False) -> None:
        self._cleanup_dialog_filter()
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
        self._append_log(
            message, severity="warning" if cancelled else "error"
        )
        self._end_bulk_logging()
        self._set_state(
            "Synchronization cancelled" if cancelled else "Synchronization failed",
            "warning" if cancelled else "error",
        )
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
        missing = self._missing_local_directories(profile)
        if missing:
            self._warn_missing_local_directories(missing, "Comparison")
            return
        self._flush_log()
        self.log.clear()
        self._last_backup_message = None
        self._last_plan_summary = None
        self._active_profile = profile
        self._comparison_profile = profile
        self._append_log("$ " + shlex.join(spec.argv()))
        self._service.compare(profile)

    def _comparison_sorted(self, column: int, order: object) -> None:
        """Report the new order of the comparison."""
        labels = {
            0: "Item",
            1: "Items",
            2: "Size",
            3: "Modified",
            4: "Actions",
            5: "Item",
            6: "Items",
            7: "Size",
            8: "Modified",
        }
        label = labels.get(int(column), "the selected column")
        direction = (
            "descending" if order == Qt.SortOrder.DescendingOrder else "ascending"
        )
        self._set_status(
            f"Sorted by {label} ({direction}). Click the header again to reverse the order.",
            "info",
        )
        self._append_log(f"STATE comparison-sorted column={column} order={direction}")

    def _overview_updated(self, changes: object) -> None:
        """Refresh the overview with the items the filters show."""
        root_name = ""
        if self._active_profile is not None:
            root_name = self._active_profile.source.path.rstrip("/").rsplit("/", 1)[-1]
        visible = self.comparison.visible_changes()
        self.overview.set_changes(list(visible), root_name)
        self._update_hidden_count()
        self._refresh_plan_summary()

    def _overview_folder_activated(self, path: str) -> None:
        """Select a folder of the overview in the tree panes."""
        self.comparison.select_path(path)

    def _log_diff_command(self, spec: object) -> None:
        """Show the staging command before its rsync run blocks the UI."""
        self._log_spec(spec)
        self.log.repaint()
        self.progress_label.repaint()

    def _open_diff_tool(self, change: object) -> None:
        if self._active_profile is None:
            return
        path = getattr(change, "path", "")
        self._set_state(f"Preparing diff for {path}...")
        self._append_log(f"Preparing diff for {path}...")
        previous_visible = self.progress_bar.isVisible()
        previous_range = (self.progress_bar.minimum(), self.progress_bar.maximum())
        previous_value = self.progress_bar.value()
        previous_text = self.progress_label.text()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("Preparing the diff tool...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            request = build_diff_request(
                self._active_profile,  # type: ignore[arg-type]
                change,
                on_command=self._log_diff_command,
                on_log=self._append_rsync_log,
            )
        except DiffToolError as exc:
            self._set_state("Diff tool unavailable", "error")
            self._set_status(str(exc), "error")
            QMessageBox.information(self, "Diff tool unavailable", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.progress_bar.setRange(*previous_range)
            self.progress_bar.setValue(previous_value)
            self.progress_bar.setVisible(previous_visible)
            self.progress_label.setText(previous_text)
        if request.staging_directory is not None:
            self._diff_staging_directories.append(request.staging_directory)
        arguments = [str(request.source), str(request.destination)]
        started, _pid = QProcess.startDetached(request.tool.executable, arguments)
        if not started:
            self._set_state("Diff tool could not start", "error")
            self._set_status(
                f"Could not start {request.tool.executable}.", "error"
            )
            QMessageBox.warning(self, "Could not start diff tool", request.tool.executable)
            return
        self._append_log("$ " + shlex.join([request.tool.executable, *arguments]))
        self._set_state(
            f"Opened {path} in {request.tool.name}.",  # type: ignore[attr-defined]
            "success",
        )

    def _comparison_started(self) -> None:
        self._begin_bulk_logging()
        self._set_hovered_action("compare")
        self._inventory_service.cancel()
        self._inventory_token = 0
        self._inventory_pending_key = None
        # The metadata of the previous comparison no longer describes the
        # destination.
        self.comparison.set_destination_metadata({})
        # Hidden items only live in memory, so a new comparison starts with
        # nothing hidden.
        hidden = getattr(self.comparison.model, "hidden", None)
        if hidden is not None:
            hidden.clear()
        self.action_filters.set_hidden_count(0)
        self.compare_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self._reset_pause_button()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Comparing...")
        self._set_state("Comparing...")
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
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Comparison cancelled")
        self._set_state("Comparison cancelled", "warning")
        self._set_status("Comparison was cancelled. The previous comparison was left unchanged.", "warning")
        self._append_log("STATE comparison-cancelled")
        self._end_bulk_logging()

    def _comparison_finished(self, result: CompareResult) -> None:
        if self._closing:
            return
        self._save_recent_profile()
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self.progress_bar.setValue(100)
        self.progress_label.setText("Comparison completed")
        self._last_changed_changes = list(result.parsed.changes)
        self.comparison.source_root = self._active_profile.source.path.rstrip("/")
        self.comparison.destination_root = self._active_profile.destination.path.rstrip("/")
        self._fetch_destination_metadata()
        self._apply_inventory_after_compare()
        self.comparison.set_stale(False)
        self._set_locations_stale(False)
        self._validated_plan = None
        self._refresh_plan_summary()
        for message in result.parsed.diagnostics:
            self._append_log(message)
        count = len(result.parsed.changes)
        self._set_state(
            f"Comparison complete: {count} changed item(s).", "success"
        )
        self._play_completion_sound("success")
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
        self.comparison.set_action_filter(selected)

    def _apply_show_hidden(self, show: bool) -> None:
        """Show the hidden items, or put them aside again."""
        if hasattr(self.comparison, "set_show_hidden"):
            self.comparison.set_show_hidden(show)
        self._refresh_plan_summary()

    def _hide_path(self, path: str) -> None:
        """Hide a folder or an item from the comparison."""
        if not hasattr(self.comparison, "hide_path"):
            return
        self.comparison.hide_path(path)
        self.action_filters.set_hidden_count(
            self.comparison.model.hidden.count()
        )
        self._refresh_plan_summary()

    def _show_path(self, path: str) -> None:
        """Show a hidden folder or item again."""
        if not hasattr(self.comparison, "show_path"):
            return
        self.comparison.show_path(path)
        self.action_filters.set_hidden_count(
            self.comparison.model.hidden.count()
        )
        self._refresh_plan_summary()

    def _update_hidden_count(self) -> None:
        """Keep the hidden item count next to the toggle up to date."""
        hidden = getattr(self.comparison.model, "hidden", None)
        count = hidden.count() if hidden is not None else 0
        self.action_filters.set_hidden_count(count)

    def _apply_inventory_after_compare(self) -> None:
        """Gather the unchanged items when the inventory runs automatically.

        The result is cached for the comparison, so the unchanged button only
        shows the cached items instead of running the inventory again. The
        unchanged items stay hidden until the user asks for them.
        """
        if not self.inventory_after_compare_button.isChecked():
            self._apply_inventory_mode()
            return
        changed = list(self._last_changed_changes)
        if self._active_profile is None:
            return
        key = self._inventory_key(self._active_profile, changed)
        if self._inventory_cache_key == key and self._inventory_cache is not None:
            return
        if self._inventory_pending_key == key and self._inventory_token:
            return
        # The compared items are shown right away, the unchanged items
        # stay hidden until the user asks for them.
        self.comparison.set_changes(changed)
        self._start_inventory(key, changed)

    def _apply_inventory_mode(self) -> None:
        """Show or hide the unchanged items of the current comparison."""
        changed = list(self._last_changed_changes)
        if self._active_profile is None:
            return
        if not self.show_unchanged.isChecked():
            self._inventory_service.cancel()
            self._inventory_token = 0
            self._inventory_pending_key = None
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_label.setText("Unchanged items hidden")
            self.comparison.set_changes(changed)
            return
        key = self._inventory_key(self._active_profile, changed)
        if self._inventory_cache_key == key and self._inventory_cache is not None:
            self._populate_unchanged(
                changed + list(self._inventory_cache),
                len(self._inventory_cache),
            )
            return
        if self._inventory_pending_key == key and self._inventory_token:
            return
        # Show the compared items right away. The unchanged items are
        # merged in when the inventory completes, so the tree never stays
        # empty and no second comparison is needed.
        self.comparison.set_changes(changed)
        self._start_inventory(key, changed)

    def _hide_unchanged(self, changed: list[object]) -> None:
        self.show_unchanged.blockSignals(True)
        self.show_unchanged.setChecked(False)
        self.show_unchanged.blockSignals(False)
        self.progress_label.setText("Unchanged items hidden")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.comparison.set_changes(changed)

    def _populate_unchanged(self, changes: list[object], unchanged: int) -> None:
        """Add the unchanged items to the comparison.

        The flat list has nothing to expand, so the rows are simply added.
        """
        self.progress_label.setText(
            f"Adding {unchanged:,} unchanged item(s) to the comparison..."
        )
        self.progress_label.repaint()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.comparison.set_changes(changes)
        finally:
            QApplication.restoreOverrideCursor()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(self._inventory_summary(unchanged))

    def _inventory_summary(self, unchanged: int) -> str:
        return f"Showing {unchanged:,} unchanged item(s)."

    def _fetch_destination_metadata(self) -> None:
        """Fill in the size and date of the destination-only objects."""
        if self._active_profile is None:
            return
        if getattr(self.comparison.model, "hidden", None) is None:
            return
        # The inventory already knows the destination metadata.
        if self.inventory_after_compare_button.isChecked():
            return
        self._metadata_token = self._metadata_service.gather(
            deepcopy(self._active_profile), list(self._changed_changes())
        )

    def _changed_changes(self) -> list[object]:
        return [
            change
            for change in self._last_changed_changes
            if getattr(change, "action", None)
            is not ChangeAction.NO_CHANGE
        ]

    def _metadata_finished(self, token: int, extra: object) -> None:
        if self._closing or token != self._metadata_token:
            return
        self._metadata_token = 0
        result = _inventory_result(extra)
        if not result.destination_metadata:
            return
        merged = dict(getattr(self.comparison, "_destination_metadata", {}) or {})
        merged.update(result.destination_metadata)
        self.comparison.set_destination_metadata(merged)
        self._append_log(
            f"Destination metadata: {len(result.destination_metadata)} object(s)."
        )

    def _start_inventory(self, key: object, changed: list[object]) -> None:
        """List both trees in the background."""
        if self._active_profile is not None:
            missing = self._missing_local_directories(self._active_profile)
            if missing:
                self._warn_missing_local_directories(missing, "Inventory")
                return
        self._inventory_pending_key = key
        self.progress_label.setText("Gathering unchanged items...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._append_log("STATE inventory-started")
        self._inventory_token = self._inventory_service.gather(
            deepcopy(self._active_profile), changed
        )

    def _inventory_progress(self, token: int, phase: str, count: int) -> None:
        if self._closing or token != self._inventory_token:
            return
        if phase == "Matching":
            self.progress_label.setText("Matching unchanged items...")
        else:
            self.progress_label.setText(
                f"Gathering unchanged items ({phase}): {count:,} objects..."
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
        if self._active_profile is None:
            return
        key = self._inventory_key(self._active_profile, changed)
        if key != self._inventory_pending_key:
            return
        result = _inventory_result(extra)
        self._inventory_cache_key = key
        self._inventory_cache = list(result.unchanged)
        # The listing knows the destination of every object, so the tree can
        # show its size and date.
        self.comparison.set_destination_metadata(result.destination_metadata)
        if self.show_unchanged.isChecked():
            self._populate_unchanged(
                changed + list(result.unchanged), len(result.unchanged)
            )
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
        self.progress_label.setText(self._inventory_summary(len(result.unchanged)))
        self._append_log(
            f"STATE inventory-complete unchanged={len(result.unchanged)}"
        )

    def _inventory_failed(self, token: int, message: str) -> None:
        if self._closing:
            return
        if token != self._inventory_token:
            return
        self._inventory_token = 0
        self._inventory_pending_key = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Inventory gathering failed")
        self._append_log(f"Inventory gathering failed: {message}")
        if self.show_unchanged.isChecked():
            self._set_status(
                "Could not gather unchanged items; showing changed items only.",
                "warning",
            )
            self.comparison.set_changes(list(self._last_changed_changes))

    def _comparison_error(self, message: str) -> None:
        if self._closing:
            return
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_label.setText("Comparison failed")
        self._set_state("Comparison failed.", "error")
        self._append_log(message, severity="error")
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

    def _append_log(
        self,
        text: str,
        *,
        rsync: bool = False,
        severity: str = "info",
    ) -> None:
        if not text:
            return
        normalized = text.rstrip("\r\n")
        if not normalized:
            return
        timestamp = datetime.now().strftime("%H:%M")
        for line in normalized.replace("\r", "\n").splitlines() or [""]:
            self._log_buffer.append((line, rsync, severity.lower(), timestamp))
        if self._bulk_logging:
            if not self._log_flush_timer.isActive():
                self._log_flush_timer.start()
            return
        self._flush_log()

    def _append_rsync_log(self, text: str) -> None:
        self._append_log(text, rsync=True)

    def _flush_log(self) -> None:
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        if not self._log_buffer:
            return
        entries = self._log_buffer
        self._log_buffer = []
        for line, rsync, severity, timestamp in entries:
            self._append_journal_line(line, timestamp, rsync, severity)
            self._write_session_log(line)

    def _append_journal_line(
        self, text: str, timestamp: str, rsync: bool, severity: str
    ) -> None:
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        time_format = QTextCharFormat()
        time_format.setForeground(QColor("#6b7280"))
        cursor.insertText(f"{timestamp} ", time_format)

        content_format = QTextCharFormat()
        if rsync:
            color = QColor("#9ca3af")
        elif severity == "warning":
            color = QColor("#0891B2")
        elif severity == "error":
            color = QColor("#B91C1C")
        elif severity == "success":
            color = QColor("#15803D")
        else:
            # Keep regular application text readable on the journal background:
            # near-white on a dark background, near-black on a light one.
            background = self.log.palette().color(QPalette.ColorRole.Base)
            color = (
                QColor("#f8fafc")
                if background.lightness() < 128
                else QColor("#111827")
            )
        content_format.setForeground(color)
        cursor.insertText(text, content_format)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _append_transient_log(self, text: str) -> None:
        """Keep rsync progress in the session log, not in the journal."""
        normalized = text.rstrip("\r\n")
        if normalized:
            self._write_session_log(normalized)

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
        settings.setValue("profile/recent", encode_text(payload))
        settings.remove("profile/recent_path")
        settings.sync()

    def _restore_recent_profile(self) -> bool:
        settings = app_settings()
        payload = decode_text(settings.value("profile/recent", "")) or ""
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
        settings.setValue(
            "profile/recent", encode_text(profile_to_json(profile))
        )
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
        settings.setValue(
            "comparison/filters", encode_text(encode_filters(self._filters))
        )
        settings.sync()

    def _restore_filters(self) -> None:
        settings = app_settings()
        payload = decode_text(settings.value("comparison/filters", "")) or ""
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
        if not self.source_edit.text().strip() or not self.destination_edit.text().strip():
            self._set_state("Enter locations to compare")
            return
        try:
            missing = self._missing_local_directories(self._profile())
        except ValueError:
            missing = ["Invalid location."]
        if missing:
            self._set_state("Enter locations to compare")
            self._set_status("Missing: " + " ".join(missing), "warning")
        else:
            self._set_state("Ready for compare")

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
        value = settings.value("comparison/inventory-after-compare", False)
        checked = (
            value
            if isinstance(value, bool)
            else str(value).strip().lower() in ("true", "1", "yes")
        )
        self.inventory_after_compare_button.setChecked(checked)

    def _inventory_after_compare_changed(self, checked: bool) -> None:
        """Remember whether the inventory runs automatically after a compare."""
        settings = app_settings()
        settings.setValue("comparison/inventory-after-compare", bool(checked))
        settings.sync()
        if (
            checked
            and self._active_profile is not None
            and self.comparison.model.changes
            and not self.comparison.model.stale
        ):
            # Turning the toggle on for an existing comparison starts the
            # inventory that would otherwise have run after the comparison.
            self._fetch_destination_metadata()
        self._apply_inventory_after_compare()

    def _shutdown_operations(self) -> None:
        """Stop every running operation before the window is destroyed."""
        self._cleanup_dialog_filter()
        for directory in self._diff_staging_directories:
            shutil.rmtree(directory, ignore_errors=True)
        self._diff_staging_directories.clear()
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
                        self,
                        "Save Profile",
                        str(profiles_directory() / "qpy-rsync-profile.json"),
                        "JSON (*.json)",
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
