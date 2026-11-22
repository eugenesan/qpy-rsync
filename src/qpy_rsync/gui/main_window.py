from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict, replace
import shlex
import shutil
import time
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QProcess, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QKeySequence,
    QPalette,
    QShortcut,
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

from qpy_rsync import __version__ as APP_VERSION
from qpy_rsync.backend.decision_filters import temporary_decision_filter
from qpy_rsync.backend.destination_sizes import (
    build_destination_size_index,
    destination_subtree_size,
)
from qpy_rsync.backend.diagnostics import debug_timing, set_timing_sink, timed
from qpy_rsync.backend.inventory import (
    InventoryResult,
    gather_destination_metadata,
    gather_source_paths,
    unfiltered_profile,
)
from qpy_rsync.backend.process_runner import ProcessState
from qpy_rsync.backend.rsync_command import (
    build_compare_spec,
    build_inventory_spec,
    build_sync_spec,
)
from qpy_rsync.backend.rsync_filters import filter_text_to_rules
from qpy_rsync.core.changes import ChangeAction, ChangeDecision
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

_COMPARE_TOOLTIP = (
    "Compare Source and Destination using an rsync dry run.\n"
    "No files are changed.\n"
    "For SSH endpoints this connects to the remote host, so the remote "
    "host must be reachable and credentials must be available."
)
_STALE_STATE_TEXT = "Stale comparison — click Compare to refresh"

_VERIFY_TOOLTIP = (
    "Optional diagnostic: check the selected decisions against the plan.\n"
    "Synchronization does not depend on this check.\n"
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
from qpy_rsync.core.enums import (
    ConflictPolicy,
    DeleteTiming,
    EndpointKind,
    Severity,
    SyncMode,
)
from qpy_rsync.core.backup_paths import resolve_backup
from qpy_rsync.core.execution_gate import ExecutionGate, ExecutionGateState
from qpy_rsync.core.units import format_size
from qpy_rsync.core.execution_plan import (
    ExecutionPlan,
    build_execution_plan,
    check_plan_freshness,
    decision_signature,
    profile_fingerprint,
)
from qpy_rsync.core.models import (
    BackupOptions,
    FilterRule,
    PreservationOptions,
    SyncProfile,
    TransferOptions,
)
from qpy_rsync.core.validation import validate_profile
from qpy_rsync.services.backup_inspection import inspect_backup_directory
from qpy_rsync.services.compare_service import CompareResult, CompareService
from qpy_rsync.services.diff_tool_service import (
    DiffTool,
    DiffToolError,
    build_diff_request,
)
from qpy_rsync.services.external_tools import (
    ExternalTool,
    ExternalToolError,
    ToolContext,
    build_tool_command,
    item_context,
    load_diff_command,
    load_tools,
    save_diff_command,
    save_tools,
)
from qpy_rsync.services.inventory_service import InventoryService
from qpy_rsync.services.plan_validation_service import (
    PlanValidationResult,
    PlanValidationService,
    compare_plan_to_changes,
)
from qpy_rsync.services.sounds import play_completion_sound
from qpy_rsync.services.sync_service import SyncResult, SyncService

from .action_colours import load_colours, save_colours, set_current_colours
from .action_filters import ActionFilterBar
from .command_preview import CommandPreview
from .controls import CONTROL_ICON_SIZE, CONTROL_SIZE
from .flat_comparison_view import FlatComparisonView
from .icons import (
    cancel_icon,
    compare_icon,
    filters_icon,
    inventory_mode_icon,
    preserve_icon,
    layout_mode_icon,
    backup_icon,
    folder_add_icon,
    folder_open_icon,
    cloud_download_icon,
    cloud_upload_icon,
    log_file_icon,
    open_icon,
    pause_icon,
    save_icon,
    profile_icon,
    restore_defaults_icon,
    settings_icon,
    swap_icon,
    synchronize_icon,
    verify_icon,
)
from .overview import OverviewPane
from .filter_editor import FilterEditorDialog
from .backup_settings import decode_backup, encode_backup
from .sync_confirmation import SyncConfirmationDialog

LAYOUT_MODES = (
    ("normal", "Normal"),
    ("focus", "Compare only"),
    ("wide", "Compare with overview"),
)

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
        self._service.on_diagnostic = self._append_log
        self._service.on_progress = self._comparison_progress
        self._service.on_transient = self._append_transient_log
        self._service.on_items = self._comparison_items
        self._active_profile: SyncProfile | None = None
        self._profile_path: Path | None = None
        self._profile_transfer = TransferOptions()
        self._profile_preservation = PreservationOptions()
        self._profile_conflict = ConflictPolicy.OVERRIDE
        self._comparison_profile: SyncProfile | None = None
        self._current_plan: ExecutionPlan | None = None
        self._plan_stale: bool = False
        self._plan_paths: list[str] = []
        self._plan_item_indices: list[int] = []
        self._plan_items: dict[str, object] = {}
        self._plan_changes: dict[str, object] = {}
        self._last_excluded_paths: set[str] = set()
        self._last_explicit_decisions: tuple[tuple[str, ChangeDecision], ...] = ()
        self._validated_plan: ExecutionPlan | None = None
        self._verified_plan: ExecutionPlan | None = None
        self._baseline_plan: ExecutionPlan | None = None
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
        # A failed listing emits `failed`, never `finished`. Without this
        # handler the busy bar and "Gathering destination metadata..." stay up
        # forever after any rsync error (missing rsync, bad SSH, bad args).
        self._metadata_service.failed.connect(self._metadata_failed)
        # Optional preload: list the source alongside the metadata so a later
        # Show unchanged needs no rsync at all.
        self._source_preload_service = InventoryService(
            self, gather=gather_source_paths
        )
        self._source_preload_service.finished.connect(
            self._source_preload_finished
        )
        self._source_preload_token = 0
        self._cached_source_paths: object | None = None
        self._showing_unchanged = False
        self._metadata_token = 0
        self._inventory_token = 0
        self._inventory_pending_key: object | None = None
        self._inventory_cache_key: object | None = None
        self._inventory_cache: list[object] | None = None
        self._dialog_filter_context: object | None = None
        # The tools the user may run on an item, and the diff tool command.
        self._external_tools: list[ExternalTool] = load_tools()
        self._diff_command: str = load_diff_command()
        # The colours that mark the actions of the comparison.
        self._action_colours = load_colours()
        set_current_colours(self._action_colours)
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
        self._verify_state = "idle"
        self._filters: list[FilterRule] = []
        self._filters_text: str = ""
        self._sound_enabled = True
        self._backup = BackupOptions()
        self._hovered_action = "compare"
        self._closing = False
        self._layout_mode = "normal"
        self._wide_overview_width: int | None = None
        self._overview_min_width: int | None = None
        self._log_file_enabled = True
        self._log_file_path = self._default_log_file_path("app")
        self._log_initialized = False
        self._log_handle = None
        self._rsync_log_path = self._default_log_file_path("rsync")
        self._rsync_log_handle = None
        self._log_size_warned = False
        self._rsync_pending: list[str] = []
        self._last_phase_started: float | None = None
        self._rsync_started_at: dict[str, float] = {}
        self._log_buffer: list[str] = []
        self._bulk_logging = False
        self._bulk_rsync = False
        self._bulk_record_count = 0
        # QPY_RSYNC_PROFILE=1 sends timing lines to stderr and the session log.
        set_timing_sink(self._append_log)
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(100)
        self._log_flush_timer.timeout.connect(self._flush_log)
        self._stale_summary_timer = QTimer(self)
        self._stale_summary_timer.setSingleShot(True)
        self._stale_summary_timer.setInterval(100)
        self._stale_summary_timer.timeout.connect(self._refresh_estimated_summary)
        # A destination listing can hang on a remote/NFS tree. Without a
        # watchdog the status stays "Comparing..." forever after the beep.
        self._metadata_watchdog = QTimer(self)
        self._metadata_watchdog.setSingleShot(True)
        self._metadata_watchdog.setInterval(60000)
        self._metadata_watchdog.timeout.connect(self._metadata_timeout)
        settings = app_settings()
        self._verification_enabled = settings.value(
            "verification/enabled", False, type=bool
        )
        self._verification_rsync = settings.value(
            "verification/rsync", False, type=bool
        )
        self._preserve_decisions = settings.value(
            "decisions/preserve", True, type=bool
        )
        self._detect_inherited_conflicts = settings.value(
            "decisions/detect-inherited", False, type=bool
        )
        self._rsync_output_logging = settings.value(
            "logging/rsync_output", False, type=bool
        )
        self._metadata_two_pass = settings.value(
            "advanced/dest_metadata_two_pass", False, type=bool
        )
        self._inventory_preload = settings.value(
            "advanced/inventory_preload", False, type=bool
        )
        self._hybrid_enabled = settings.value(
            "advanced/hybrid_view", False, type=bool
        ) or os.environ.get("QPY_HYBRID_VIEW", "") == "1"
        self._metadata_service.set_gather_option(
            "two_pass", self._metadata_two_pass
        )
        self._last_compare_locations: tuple[str, str] | None = None
        self._last_compare_filters: str = ""
        self._preserve_for_compare = True
        self._preserve_reason = ""
        self._preserve_before_force: bool | None = None
        self._metadata_pending = False
        self._comparison_announced = False
        self._compare_generation = 0
        self._active_compare_generation = 0
        self._last_compare_count = 0
        self._next_compare_locations: tuple[str, str] | None = None
        self._next_compare_filters: str = ""
        self._build_ui()
        self._plan_exec_hint: object | None = None
        self._skip_next_plan_rebuild = False
        self._hybrid_view: object | None = None
        self._hybrid_originals: dict = {}
        if self._hybrid_enabled:
            self._enable_hybrid_view()
        self._restore_window_state()
        profile_loaded = self._restore_recent_profile()
        if not profile_loaded:
            self._restore_backup()
        self._restore_logging_settings()
        if profile_loaded:
            self._append_log(
                f"Profile loaded automatically: {self._profile_name()}",
                severity="info",
            )
        filter_directories = app_settings().value(
            "comparison/filter-directories", False, type=bool
        )
        self.action_filters.directory_filter_box.blockSignals(True)
        self.action_filters.directory_filter_box.setChecked(filter_directories)
        self.action_filters.directory_filter_box.blockSignals(False)
        self.comparison.set_filter_directories(filter_directories)
        self._sound_enabled = app_settings().value(
            "sound/enabled", True, type=bool
        )
        self._update_verification_visibility()
        self._update_startup_status()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None
        self._refresh_profile_marker()

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
        self.comparison.model.preserve_decisions = self._preserve_decisions
        self.comparison.diff_requested.connect(self._open_diff_tool)
        self.comparison.decision_changed.connect(self._on_decision_changed)
        self.comparison.model.history_changed.connect(self._update_decision_actions)
        self.comparison.stale_changed.connect(self._update_stale_indicators)
        self.comparison.changes_updated.connect(self._overview_updated)
        self.comparison.reset_exclusions_requested.connect(self._reset_exclusions)
        self.comparison.tool_requested.connect(self._run_external_tool)
        self.comparison.set_external_tools(self._external_tools)
        self.comparison.sort_changed.connect(self._comparison_sorted)

        if hasattr(self.comparison, "filter_requested"):
            self.comparison.filter_requested.connect(self._add_filter_phrase)
        self.comparison.controls.setParent(root)

        controls = QHBoxLayout()
        controls.addWidget(vertical_separator())
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
        self.compare_button = QToolButton()
        self.compare_button.setIcon(compare_icon())
        self.compare_button.setToolTip(_COMPARE_TOOLTIP)
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
        self.validate_plan_button.setAccessibleName("Verify Decisions")
        self.synchronize_button = QToolButton()
        self.synchronize_button.setIcon(synchronize_icon())
        self.synchronize_button.setAccessibleName("Synchronize")
        self.synchronize_button.setToolTip(
            "Open the confirmation dialog and review the exact rsync command,\n"
            "decision rules and counts before writing. Verification is an\n"
            "optional diagnostic and is not required to synchronize."
        )
        self.synchronize_button.setEnabled(False)
        self.validate_plan_button.setEnabled(False)
        self.filters_button = QToolButton()
        self.filters_button.setIcon(filters_icon())
        self.filters_button.setToolTip("Edit the persistent filter rules")
        self.filters_button.setAccessibleName("Filters")
        self.profile_menu = QMenu(self)
        self.profile_menu.aboutToShow.connect(self._update_profile_menu)
        self.profile_button = QToolButton()
        self.profile_button.setIcon(profile_icon())
        self.profile_button.setToolTip("Manage profiles")
        self.profile_button.setAccessibleName("Manage Profiles")
        self.profile_button.setMenu(self.profile_menu)
        self.profile_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        # Backwards-compatible aliases for the buttons this one replaces.
        self.load_profile_button = self.profile_button
        self.save_profile_button = self.profile_button
        self.unload_profile_button = self.profile_button
        self.layout_menu = QMenu(self)
        self.layout_menu.aboutToShow.connect(self._refresh_layout_button)
        self.layout_actions: dict[str, object] = {}
        from PySide6.QtGui import QAction

        for mode, label in LAYOUT_MODES:
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, m=mode: self._set_layout_mode(m)
            )
            self.layout_menu.addAction(action)
            self.layout_actions[mode] = action
        self.layout_button = QToolButton()
        self.layout_button.setIcon(layout_mode_icon())
        self.layout_button.setToolTip("Compare layout")
        self.layout_button.setAccessibleName("Compare layout")
        self.layout_button.setMenu(self.layout_menu)
        self.layout_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.backup_open = self._external_open_button(
            "backup-open-button",
            backup_icon(),
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
            self.profile_button,
            self.layout_button,
            self.backup_open,
            self.log_file_open,
            self.settings_button,
        ):
            button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
            button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.inventory_after_compare_button.toggled.connect(
            self._inventory_after_compare_changed
        )
        controls.addWidget(self.compare_button)
        self.preserve_button = QToolButton()
        self.preserve_button.setObjectName("preserve-decisions")
        self.preserve_button.setAccessibleName("Preserve decisions")
        self.preserve_button.setCheckable(True)
        self.preserve_button.setChecked(self._preserve_decisions)
        self.preserve_button.setIconSize(
            QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE)
        )
        self.preserve_button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.preserve_button.toggled.connect(self._preserve_toggled)
        self._update_preserve_button()
        controls.addWidget(self.preserve_button)
        controls.addWidget(self.inventory_after_compare_button)
        for widget in (
            self.validate_plan_button,
            self.synchronize_button,
            self.cancel_button,
            self.pause_button,
            None,
            self.filters_button,
            self.profile_button,
            self.backup_open,
            self.log_file_open,
            self.settings_button,
        ):
            if widget is None:
                # A line between the operations and the rest of the toolbar.
                controls.addWidget(vertical_separator())
            else:
                controls.addWidget(widget)
        controls.addWidget(vertical_separator())
        controls.addWidget(self.comparison.controls, 1)
        # The layout switch sits inside the comparison toolbar, immediately
        # to the left of the application menu button.
        comparison_layout = self.comparison.controls.layout()
        comparison_layout.insertWidget(
            comparison_layout.indexOf(self.comparison.menu_button),
            self.layout_button,
        )
        layout.addLayout(controls)
        self._controls_layout = controls

        locations = QHBoxLayout()
        source_panel = self._location_panel("Source", self.source_edit, trailing=True)
        self.action_filters = ActionFilterBar(self)
        self.action_filters.changed.connect(self._apply_action_filters)
        self.action_filters.excluded_toggled.connect(self._apply_show_excluded)
        self.action_filters.reset_exclusions_requested.connect(self._reset_exclusions)
        self.action_filters.directory_filter_toggled.connect(
            self._filter_directories_changed
        )
        self.action_filters.unchanged_toggled.connect(self._apply_inventory_mode)
        self.action_filters.conflicts_toggled.connect(
            self.comparison.model.set_conflicts_only
        )
        self._update_conflict_ui()
        self.show_unchanged = self.action_filters.unchanged_box
        destination_panel = self._location_panel("Destination", self.destination_edit)
        # The direction line above the checkboxes names both sides, so the
        # Source and Destination glyphs are not needed.
        # The action filters sit on their own; the Source and Destination
        # glyphs above them were redundant, so the row is just the filters.
        filter_column = QWidget(self)
        filter_column_layout = QVBoxLayout(filter_column)
        filter_column_layout.setContentsMargins(0, 0, 0, 0)
        filter_column_layout.setSpacing(0)
        filter_column_layout.addWidget(
            self.action_filters, 0, Qt.AlignmentFlag.AlignBottom
        )
        locations.addWidget(source_panel, 40)
        locations.addWidget(filter_column, 0, Qt.AlignmentFlag.AlignBottom)
        locations.addWidget(vertical_separator())
        locations.addWidget(destination_panel, 40)
        layout.addLayout(locations)
        self._locations_layout = locations

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter = splitter
        splitter.splitterMoved.connect(self._main_splitter_moved)
        splitter.addWidget(self.comparison)
        self.log_panel = QWidget(self)
        log_panel = self.log_panel
        log_layout = QHBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.log_splitter = log_splitter
        log_splitter.setChildrenCollapsible(False)
        log_splitter.setHandleWidth(6)
        log_column = QWidget(self)
        log_layout_column = QVBoxLayout(log_column)
        log_layout_column.setContentsMargins(0, 0, 0, 0)
        log_layout_column.setSpacing(2)
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
        self._overview_min_width = self.overview.minimumWidth()
        self.overview.folder_activated.connect(self._overview_folder_activated)
        self.overview.exclusion_requested.connect(self._exclude_path)
        self.overview.restore_requested.connect(self._restore_path)
        self.overview.filter_requested.connect(self._add_filter_phrase)
        self._install_navigation_shortcuts()
        log_splitter.addWidget(self.overview)
        log_splitter.setStretchFactor(0, 1)
        log_splitter.setStretchFactor(1, 0)
        # The overview carries the statistics bar, so it gets the room.
        overview_default = 520 + self.overview.fontMetrics().horizontalAdvance("0") * 15
        log_splitter.setSizes([680, overview_default])
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
        ):
            button.setToolTip(with_shortcut(button.toolTip(), shortcut))
        self.profile_button.setToolTip("Manage profiles (F2/F3, edit F4)")
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
            file_menu, "Save Profile", "F2", self._save_current_profile
        )
        self._add_action(
            file_menu, "Save Profile As...", "", self._save_profile
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit", "Ctrl+Q", self.close)

        edit_menu = menu_bar.addMenu("&Edit")
        self.undo_decision_action = self._add_action(
            edit_menu, "Undo Decision", "Ctrl+Z", self.comparison.undo_decision
        )
        self.redo_decision_action = self._add_action(
            edit_menu, "Redo Decision", "Ctrl+Shift+Z", self.comparison.redo_decision
        )
        self.reset_decisions_action = self._add_action(
            edit_menu, "Reset Decisions", "", self.comparison.reset_all_decisions
        )
        edit_menu.addSeparator()
        self._add_action(
            edit_menu, "Find in List", "Ctrl+F", self.comparison.focus_search
        )
        self._add_action(
            edit_menu, "Find Next", "Ctrl+G", self.comparison.find_next
        )
        self._add_action(
            edit_menu, "Find Previous", "Ctrl+Shift+G", self.comparison.find_previous
        )
        self._add_action(edit_menu, "Profile", "F4", self._edit_profile)
        self._add_action(edit_menu, "Settings", "Ctrl+,", self._edit_settings)

        view_menu = menu_bar.addMenu("&View")
        self.view_layout_actions: dict[str, object] = {}
        for mode, label in LAYOUT_MODES:
            action = self._add_action(
                view_menu, label, "", lambda _checked=False, m=mode: self._set_layout_mode(m)
            )
            action.setCheckable(True)
            self.view_layout_actions[mode] = action
        view_menu.addSeparator()
        self._add_action(
            view_menu, "Next layout", "Ctrl+Tab", self._cycle_layout_forward
        )
        self._add_action(
            view_menu, "Previous layout", "Ctrl+Shift+Tab", self._cycle_layout_backward
        )

        actions_menu = menu_bar.addMenu("&Actions")
        self._add_action(
            actions_menu,
            "Reset All Decisions",
            "",
            self.comparison.reset_all_decisions,
        )
        self._add_action(
            actions_menu, "Method", "F12", self._cycle_sync_mode
        )
        actions_menu.addSeparator()
        self._add_action(actions_menu, "Compare", "F5", self._compare)
        self._add_action(actions_menu, "Inventory", "F6", self._toggle_inventory)
        self._add_action(actions_menu, "Filters", "F7", self._edit_filters)
        self.verify_action = self._add_action(
            actions_menu, "Verify Decisions", "F8", self._validate_selected_plan
        )
        self._add_action(
            actions_menu, "Synchronize", "F9", self._show_sync_confirmation
        )
        self._add_action(
            actions_menu, "Cancel", "F10", self._cancel_active_operation
        )
        self._add_action(actions_menu, "Pause", "F11", self._toggle_pause)
        self._update_decision_actions()
        self._update_verification_visibility()
        actions_menu.addSeparator()
        self._add_action(
            actions_menu,
            "Collapse All Folders",
            "",
            self.comparison.collapse_all,
        )
        self._add_action(
            actions_menu,
            "Expand All Folders",
            "",
            self.comparison.expand_all,
        )

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

    def _configured_destination_is_local(self) -> bool:
        try:
            destination = parse_endpoint(self.destination_edit.text())
        except ValueError:
            return False
        return destination.kind is EndpointKind.LOCAL

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
            # The button keeps its menu so the backup settings stay reachable
            # even when no directory is configured yet.
            backup.setEnabled(True)
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

    def _open_profiles_directory(self) -> None:
        self._open_path(profiles_directory(), "profiles directory")

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
        if title == "Source":
            # Keep Swap away from Compare: it sits with the Source controls.
            row.addWidget(self.swap_button)
        open_button = self._external_open_button(
            f"{title.lower()}-open-button",
            cloud_upload_icon() if title == "Source" else cloud_download_icon(),
            f"Open the {title} directory",
            lambda: self._open_location_directory(title),
        )
        if title == "Source":
            self.source_open_button = open_button
        else:
            self.destination_open_button = open_button
        row.addWidget(open_button)
        browse = QToolButton()
        browse.setIcon(folder_add_icon())
        browse.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        browse.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        browse.setToolTip(f"Browse to {title} location")
        browse.setAccessibleName(f"Browse to {title} location")
        browse.clicked.connect(lambda: self._browse(edit))
        if title == "Source":
            self.source_browse_button = browse
        else:
            self.destination_browse_button = browse
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
    def _log_directory() -> Path:
        cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
        root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
        return root / "qpy-rsync"

    def _profile_name(self) -> str:
        """The name used for the ad-hoc profile and for per-profile logs."""
        if self._profile_path is not None:
            return self._profile_path.stem or "default"
        return "default"

    def _default_log_file_path(self, kind: str = "app") -> Path:
        import re

        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", self._profile_name()).strip("._") or "default"
        return self._log_directory() / f"{kind}-{slug}.log"

    def _update_log_paths(self) -> None:
        """App and rsync logs are kept separately, one pair per profile."""
        app_path = self._default_log_file_path("app")
        rsync_path = self._default_log_file_path("rsync")
        if app_path == self._log_file_path and rsync_path == self._rsync_log_path:
            return
        self._flush_log()
        self._close_session_log()
        self._close_rsync_log()
        self._log_file_path = app_path
        self._rsync_log_path = rsync_path
        self._log_size_warned = False
        self.log_file_edit.setText(str(app_path))

    def _restore_logging_settings(self) -> None:
        settings = app_settings()
        self._log_file_enabled = settings.value("logging/enabled", True, type=bool)
        self._update_log_paths()
        self.log_file_checkbox.blockSignals(True)
        self.log_file_checkbox.setChecked(self._log_file_enabled)
        self.log_file_checkbox.blockSignals(False)
        self._update_logging_controls()

    def _logging_settings_changed(self, _checked: bool | None = None, *, save: bool = True) -> None:
        self._flush_log()
        self._close_session_log()
        self._log_file_enabled = self.log_file_checkbox.isChecked()
        self._update_log_paths()
        self._update_logging_controls()
        if save:
            settings = app_settings()
            settings.setValue("logging/enabled", self._log_file_enabled)
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

    @staticmethod
    def _app_identity() -> str:
        commit = "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent.parent.parent,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                commit = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return f"qpy-rsync {APP_VERSION} ({commit})"

    def _open_log(self, path: Path, handle):
        if handle is not None:
            return handle
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        handle.write(
            f"\n===== qpy-rsync session {datetime.now().astimezone().isoformat()} "
            f"[{self._app_identity()}] =====\n"
        )
        handle.flush()
        return handle

    def _open_session_log(self):
        self._log_handle = self._open_log(self._log_file_path, self._log_handle)
        self._log_initialized = True
        return self._log_handle

    def _open_rsync_log(self):
        self._rsync_log_handle = self._open_log(
            self._rsync_log_path, self._rsync_log_handle
        )
        return self._rsync_log_handle

    @staticmethod
    def _close_handle(handle):
        if handle is not None:
            try:
                handle.flush()
            finally:
                handle.close()

    def _close_session_log(self) -> None:
        self._close_handle(self._log_handle)
        self._log_handle = None
        self._log_initialized = False

    def _close_rsync_log(self) -> None:
        self._flush_rsync_pending()
        self._close_handle(self._rsync_log_handle)
        self._rsync_log_handle = None

    def _write_session_log(self, text: str, *, rsync: bool = False) -> None:
        if not self._log_file_enabled:
            return
        handle = self._open_rsync_log() if rsync else self._open_session_log()
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for line in text.splitlines() or [""]:
            handle.write(f"{timestamp} {line}\n")
        # Buffered writes avoid one fsync (and one open/close) per rsync line.
        handle.flush()
        if not rsync:
            self._check_log_size()

    def _check_log_size(self) -> None:
        if self._log_size_warned:
            return
        try:
            size = self._log_file_path.stat().st_size
        except OSError:
            return
        if size < 1_000_000_000:
            return
        self._log_size_warned = True
        self._append_log(
            "The application log reached 1 GB. Old entries can be removed "
            "with the Log button's context menu entry \"Clear Log\".",
            severity="logsize",
        )

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
        self._refresh_profile_marker()
        if self.comparison.model.changes and not self.comparison.model.stale:
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

    def _preserve_tooltip(self) -> str:
        if self.preserve_button.isChecked():
            return (
                "Preserve decisions: ON\n"
                "Manual include and exclude decisions survive the next "
                "comparison, even when the reported action of an item changed.\n"
                "Click to turn it off and start fresh; Compare will then ask "
                "for confirmation before discarding the decisions."
            )
        if self.comparison.model.stale:
            return (
                "Preserve decisions: OFF (forced by a stale comparison)\n"
                "The locations, profile or filters changed, so the app turned "
                "preservation off to avoid applying old decisions to a "
                "different job.\n"
                "Click to keep the decisions anyway on the next Compare."
            )
        return (
            "Preserve decisions: OFF\n"
            "The next Compare will discard every manual decision and start "
            "from the rsync results. Compare asks for confirmation first.\n"
            "Click to keep the decisions instead."
        )

    def _update_preserve_button(self) -> None:
        """Show the state with the same badge style as the other buttons."""
        on = self.preserve_button.isChecked()
        forced_off = not on and self.comparison.model.stale
        self.preserve_button.setIcon(
            preserve_icon(active=on, warning=forced_off)
        )
        self.preserve_button.setToolTip(self._preserve_tooltip())

    def _set_preserve_checked(self, checked: bool) -> None:
        self.preserve_button.blockSignals(True)
        self.preserve_button.setChecked(checked)
        self.preserve_button.blockSignals(False)
        self._update_preserve_button()

    def _preserve_toggled(self, enabled: bool) -> None:
        # A manual click overrides the automatic stale-state handling.
        self._preserve_before_force = None
        self._preserve_decisions = bool(enabled)
        self.comparison.model.preserve_decisions = self._preserve_decisions
        self._update_preserve_button()
        settings = app_settings()
        settings.setValue("decisions/preserve", self._preserve_decisions)
        settings.sync()
        self._append_log(
            "Decision preservation "
            + ("enabled" if self._preserve_decisions else "disabled")
            + "."
        )

    def _prepare_decision_preservation(self, profile: SyncProfile) -> None:
        """Decide whether this comparison may keep the existing decisions.

        A different location or a changed filter set means the decisions
        describe a different job, so they are reset even when the toolbar
        toggle is on. Those are rational, logged exceptions rather than
        software failures.
        """
        locations = (profile.source.rsync_operand(), profile.destination.rsync_operand())
        reason = ""
        if (
            self._last_compare_locations is not None
            and locations != self._last_compare_locations
        ):
            reason = "Source or Destination changed"
        elif self._last_compare_filters and self._filters_text != self._last_compare_filters:
            reason = "filter rules changed"
        # A deliberately re-checked box overrides the automatic exception.
        forced = bool(reason) and self.preserve_button.isChecked()
        self._preserve_for_compare = self._preserve_decisions and (
            not reason or forced
        )
        self._preserve_reason = "" if forced else reason
        if forced:
            self._append_log(
                f"Keeping decisions although {reason}, as requested."
            )
        self._next_compare_locations = locations
        self._next_compare_filters = self._filters_text

    def _update_conflict_ui(self) -> None:
        """Show conflict review controls only for the opt-in detection."""
        enabled = bool(self._detect_inherited_conflicts)
        self.comparison.model.conflicts_visible = enabled
        self.action_filters.conflicts_box.setVisible(enabled)
        if not enabled:
            self.action_filters.conflicts_box.setChecked(False)

    def _update_verification_visibility(self) -> None:
        """Show the diagnostic only when it is enabled in Advanced settings."""
        enabled = bool(getattr(self, "_verification_enabled", False))
        button = getattr(self, "validate_plan_button", None)
        if button is not None:
            button.setVisible(enabled)
        action = getattr(self, "verify_action", None)
        if action is not None:
            action.setVisible(enabled)
            action.setEnabled(enabled)

    def _update_decision_actions(self) -> None:
        """Enable the history actions from the decision model's state."""
        history = self.comparison.model.decision_history
        self.undo_decision_action.setEnabled(history.can_undo)
        self.redo_decision_action.setEnabled(history.can_redo)
        self.reset_decisions_action.setEnabled(
            self.comparison.model.decisions.has_explicit()
        )

    def _update_stale_indicators(self, stale: bool) -> None:
        """Use the same three-state badge as the filter and profile buttons."""
        fresh = bool(self.comparison.model.changes) and not stale
        self.compare_button.setIcon(compare_icon(info=fresh, warning=stale))
        self._update_preserve_button()
        # A stale comparison means the locations, profile or filters changed.
        # Preserving decisions across it would silently apply old choices to
        # a different job, so it turns preservation off and lights the button
        # indicator. The button stays clickable: the user may check it again
        # to force preservation despite the changed locations or filters.
        if stale and self.preserve_button.isChecked():
            # Remember the user's setting so a fresh comparison can restore it.
            self._preserve_before_force = True
            self._set_preserve_checked(False)
            self._preserve_decisions = False
            self.comparison.model.preserve_decisions = False
            self._append_log(
                "Preserve decisions turned off: the comparison is stale "
                "because the locations, profile or filters changed. Check it "
                "again before Compare to keep decisions intentionally."
            )
        plan_warning = stale or self._plan_stale
        self.validate_plan_button.setIcon(
            verify_icon(
                info=self._verify_state == "verified" and not plan_warning,
                warning=plan_warning,
            )
        )
        if stale:
            self.compare_button.setToolTip(
                "STALE: this comparison no longer matches the current profile.\n"
                "Click Compare (F5) to refresh it."
            )
            self.validate_plan_button.setToolTip(
                "Compare again before Verify Decisions can run."
            )
            current = self.status_edit.text()
            if "stale" not in current.casefold():
                self._set_state(_STALE_STATE_TEXT, "stale")
            self.state_label.setStyleSheet("color: #EA580C; font-weight: bold;")
        else:
            self.compare_button.setToolTip(_COMPARE_TOOLTIP)
            self._set_verify_state(self._verify_state)
            self.state_label.setStyleSheet("")
            if self.status_edit.text() == _STALE_STATE_TEXT:
                self._update_startup_status()

    def _set_state(self, text: str, severity: str = "info") -> None:
        """Update the current operation state shown in the status bar."""
        severity = severity.lower()
        colors = {
            "warning": "#0891B2",
            "logsize": "#EA580C",
            "stale": "#EA580C",
            "error": "#B91C1C",
            "success": "#15803D",
        }
        comparison = getattr(self, "comparison", None)
        if (
            comparison is not None
            and comparison.model.stale
            and text in {"", "Ready for compare"}
        ):
            text, severity = _STALE_STATE_TEXT, "stale"
        self.status_edit.setToolTip(text)
        self._apply_status_style(colors.get(severity, ""))
        self.status_edit.setText(text.replace("\n", " "))
        # The "State:" label is orange only while the comparison is stale.
        if severity != "stale":
            self.state_label.setStyleSheet("")

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
            name="default",
            source=parse_endpoint(self.source_edit.text()),
            destination=parse_endpoint(self.destination_edit.text()),
            filters=list(self._filters),
            filter_text=self._filters_text,
            backup=BackupOptions(
                directory=self.backup_edit.text().strip(),
                protect_nested=self.protect_backup.isChecked(),
            ),
            transfer=TransferOptions(
                **{
                    **asdict(self._profile_transfer),
                    "sync_mode": SyncMode(self.sync_mode.currentData()),
                    "delete_timing": DeleteTiming(
                        self._profile_transfer.delete_timing
                    ),
                }
            ),
            preservation=PreservationOptions(**asdict(self._profile_preservation)),
            conflict_policy=self._profile_conflict,
            inventory_after_compare=self.inventory_after_compare_button.isChecked(),
        )

    def _cycle_sync_mode(self) -> None:
        """Move to the next synchronization method."""
        count = self.sync_mode.count()
        if count:
            self.sync_mode.setCurrentIndex((self.sync_mode.currentIndex() + 1) % count)

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
        self._refresh_profile_marker()

    def _edit_filters(self) -> None:
        self._edit_profile("filters")

    def _edit_profile(self, section: str = "options") -> None:
        from .profile_editor import ProfileEditorDialog

        dialog = ProfileEditorDialog(self._profile(), self, section)
        if not dialog.exec():
            return
        updated = dialog.profile()
        self._profile_transfer = deepcopy(updated.transfer)
        self._profile_preservation = deepcopy(updated.preservation)
        self._profile_conflict = updated.conflict_policy
        self.inventory_after_compare_button.blockSignals(True)
        self.inventory_after_compare_button.setChecked(updated.inventory_after_compare)
        self.inventory_after_compare_button.blockSignals(False)
        self.backup_edit.setText(updated.backup.directory)
        self.protect_backup.setChecked(updated.backup.protect_nested)
        self._backup_changed()
        index = self.sync_mode.findData(updated.transfer.sync_mode)
        if index >= 0:
            self.sync_mode.setCurrentIndex(index)
        if updated.filter_text != self._filters_text:
            self._filters_text = updated.filter_text
            self._filters = filter_text_to_rules(self._filters_text)
            self._update_filter_summary(stale=True)
            self.comparison.set_stale(True)
            self._invalidate_plan_context()
            self._set_state(
                "Stale comparison: filter rules changed. Compare again to refresh results.",
                "stale",
            )
        self._refresh_profile_marker()

    def _configure_open_button_menu(self, button: QToolButton, section: str) -> None:
        """Give an open button a right-click menu that leads to its settings."""
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda point, b=button, s=section: self._open_button_menu(b, point, s)
        )

    def _open_button_menu(self, button: QToolButton, point: object, section: str) -> None:
        menu = QMenu(button)
        open_action = menu.addAction(button.toolTip())
        if section == "backup":
            open_action.setEnabled(
                bool(self.backup_edit.text().strip())
                and self._configured_destination_is_local()
            )
        elif section == "logging":
            open_action.setEnabled(bool(self.log_file_edit.text().strip()))
        clear = None
        if section == "logging":
            clear = menu.addAction("Clear Log")
        configure = menu.addAction("Configure...")
        selected = menu.exec(button.mapToGlobal(point))
        if selected is open_action:
            if open_action.isEnabled():
                button.click()
        elif selected is clear:
            self._clear_log()
        elif selected is configure:
            if section == "backup":
                self._edit_profile("backup")
            else:
                self._edit_settings(section)

    def _clear_log(self) -> None:
        """Empty both log files of the current profile and keep logging."""
        self._close_session_log()
        self._close_rsync_log()
        try:
            for path in (self._log_file_path, self._rsync_log_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
        except OSError as exc:
            self._set_status(f"Could not clear the log files: {exc}", "error")
            return
        self._log_size_warned = False
        self._write_session_log("The application log was cleared.")
        self._append_log(
            f"Log files cleared: {self._log_file_path}, {self._rsync_log_path}",
            severity="info",
        )
        self._set_status("Log files cleared.")

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
            tools=self._external_tools,
            diff_command=self._diff_command,
            colours=self._action_colours,
            verification_enabled=self._verification_enabled,
            verification_rsync=self._verification_rsync,
            detect_inherited_conflicts=self._detect_inherited_conflicts,
            rsync_output_logging=self._rsync_output_logging,
            metadata_two_pass=self._metadata_two_pass,
            inventory_preload=self._inventory_preload,
            hybrid_view=self._hybrid_enabled,
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
            self._verification_enabled = dialog.verification_enabled()
            self._verification_rsync = dialog.verification_rsync()
            settings = app_settings()
            settings.setValue("verification/enabled", self._verification_enabled)
            settings.setValue("verification/rsync", self._verification_rsync)
            self._detect_inherited_conflicts = (
                dialog.detect_inherited_conflicts()
            )
            settings.setValue(
                "decisions/detect-inherited", self._detect_inherited_conflicts
            )
            self._rsync_output_logging = dialog.rsync_output_logging()
            settings.setValue("logging/rsync_output", self._rsync_output_logging)
            self._metadata_two_pass = dialog.metadata_two_pass()
            self._inventory_preload = dialog.inventory_preload()
            settings.setValue(
                "advanced/dest_metadata_two_pass", self._metadata_two_pass
            )
            settings.setValue(
                "advanced/inventory_preload", self._inventory_preload
            )
            self._metadata_service.set_gather_option(
                "two_pass", self._metadata_two_pass
            )
            settings.sync()
            self._update_verification_visibility()
            self._update_conflict_ui()
            hybrid = dialog.hybrid_view()
            if hybrid != self._hybrid_enabled:
                if hybrid:
                    detail = (
                        "The native comparison views are experimental. They "
                        "keep rsync, decisions, plan and validation in Python, "
                        "but draw the lists and overview natively. No data is "
                        "lost by switching. The change applies immediately; "
                        "run Compare again if anything looks out of date."
                    )
                else:
                    detail = (
                        "Returning to the Python view requires rebuilding its "
                        "model from scratch. On a large comparison this can "
                        "take minutes and the UI will be busy while it runs. "
                        "No data is lost; decisions and the plan are kept."
                    )
                answer = QMessageBox.question(
                    self,
                    "Switch comparison view?",
                    detail + "\n\nSwitch now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    hybrid = self._hybrid_enabled
                settings.setValue("advanced/hybrid_view", hybrid)
                settings.sync()
                self._hybrid_enabled = hybrid
                if hybrid:
                    self._enable_hybrid_view()
                    if self._hybrid_view is None:
                        QMessageBox.warning(
                            self, "Native views unavailable",
                            "The native comparison extension is not built or "
                            "could not be loaded. The Python view stays active.",
                        )
                        self._hybrid_enabled = False
                        settings.setValue("advanced/hybrid_view", False)
                        settings.sync()
                else:
                    self._disable_hybrid_view()
            self._external_tools = dialog.external_tools()
            self._diff_command = dialog.diff_command()
            save_tools(self._external_tools)
            save_diff_command(self._diff_command)
            self.comparison.set_external_tools(self._external_tools)
            self._apply_action_colours(dialog.action_colours())
        # The panels return to their holder in any case.
        self._update_external_open_states()

    def _apply_action_colours(self, colours: dict[object, str | None]) -> None:
        """Use the colours of the actions and repaint the list."""
        self._action_colours = colours
        set_current_colours(colours)
        save_colours(colours)
        self.action_filters.refresh_icons()
        self.comparison.model.action_colours_changed()
        if self._hybrid_view is not None:
            self._hybrid_view.set_action_colours()

    def _add_filter_phrase(self, label: str, path: object) -> None:
        """Add an rsync exclude rule produced by the context menu."""
        from qpy_rsync.core.enums import FilterRuleType
        from qpy_rsync.core.models import FilterRule

        if not isinstance(path, str):
            return
        pattern = label.strip()
        if not pattern:
            return
        if pattern in [line.strip() for line in self._filters_text.splitlines()]:
            self._append_log(f"Filter already present: {pattern}", severity="warning")
            return
        self._filters_text = self._filters_text.rstrip("\n")
        prefix = "\n" if self._filters_text else ""
        self._filters_text = f"{self._filters_text}{prefix}# Added from {path}\n{pattern}"
        self._filters = filter_text_to_rules(self._filters_text)
        self._update_filter_summary(stale=True)
        self.comparison.set_stale(True)
        self._invalidate_plan_context()
        self._set_state(
            f"Stale comparison: added the filter {pattern}. "
            "Compare again to refresh the results.",
            "stale",
        )
        self._append_log(f"Added rsync filter: {pattern}", severity="info")

    # ------------------------------------------------------------------ #
    # Profile management
    # ------------------------------------------------------------------ #
    @staticmethod
    def _same_profile(a, b) -> bool:
        if a is None or b is None:
            return False
        import json

        # Compare the serialized form so enums and their string values compare
        # equal, the way they are stored in a profile.
        left = json.loads(profile_to_json(a))
        right = json.loads(profile_to_json(b))
        for key in ("profile_id", "name"):
            left.pop(key, None)
            right.pop(key, None)
        return left == right

    def _profile_is_modified(self) -> bool:
        try:
            current = self._profile()
        except (TypeError, ValueError):
            return False
        baseline = getattr(self, "_baseline_profile", None)
        if self._same_profile(current, baseline):
            return False
        if baseline is not None:
            left = current.to_dict()
            right = baseline.to_dict()
            for key in ("profile_id", "name"):
                left.pop(key, None)
                right.pop(key, None)
            for key in left:
                if left[key] != right.get(key):
                    debug_timing(
                        "profile.modified_field",
                        field=key,
                        current=repr(left[key]),
                        baseline=repr(right.get(key)),
                    )
                    break
        return True

    def _refresh_profile_marker(self) -> None:
        loaded = self._profile_path is not None
        modified = loaded and self._profile_is_modified()
        self.profile_button.setIcon(profile_icon(loaded=loaded, modified=modified))
        name = self._profile_path.name if self._profile_path else "no profile"
        state = " (changed)" if modified else ""
        self.profile_button.setToolTip(
            f"Manage profiles — {name}{state} (F2 save, F3 load, F4 edit)"
        )

    def _recent_profile_paths(self) -> list[Path]:
        """Recently used profiles, then the ones found in the profile folder."""
        settings = app_settings()
        payload = decode_text(settings.value("profile/recent_paths", "")) or ""
        remembered: list[Path] = []
        if payload:
            try:
                import json

                raw = json.loads(payload)
                if isinstance(raw, list):
                    remembered = [Path(str(item)).expanduser() for item in raw]
            except (ValueError, TypeError):
                remembered = []
        directory = profiles_directory()
        on_disk = sorted(
            (path for path in directory.glob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        paths: list[Path] = []
        for path in [*remembered, *on_disk]:
            if path.is_file() and path not in paths:
                paths.append(path)
        return paths[:10]

    def _remember_profile_path(self, path: Path) -> None:
        self._profile_path = path
        self._update_log_paths()
        import json

        paths = [path] + [
            existing for existing in self._recent_profile_paths() if existing != path
        ]
        settings = app_settings()
        settings.setValue(
            "profile/recent_paths",
            encode_text(json.dumps([str(item) for item in paths[:10]])),
        )
        settings.setValue("profile/current_path", encode_text(str(path)))
        settings.sync()
        self._refresh_profile_marker()

    def _update_profile_menu(self) -> None:
        menu = self.profile_menu
        menu.clear()
        from PySide6.QtGui import QAction

        load = menu.addAction("Load...")
        load.triggered.connect(self._load_profile)
        save = menu.addAction("Save")
        save.triggered.connect(self._save_current_profile)
        menu.addSeparator()
        recent = self._recent_profile_paths()
        if recent:
            for path in recent:
                action = menu.addAction(path.name)
                action.setToolTip(str(path))
                action.setCheckable(True)
                action.setChecked(path == self._profile_path)
                action.triggered.connect(
                    lambda _checked=False, p=path: self._open_recent_profile(p)
                )
        else:
            note = menu.addAction("No recent profiles")
            note.setEnabled(False)
        menu.addSeparator()
        edit = menu.addAction("Edit...")
        edit.triggered.connect(self._edit_profile)
        save_as = menu.addAction("Save As...")
        save_as.triggered.connect(self._save_profile)
        open_dir = menu.addAction("Open profiles directory")
        open_dir.triggered.connect(self._open_profiles_directory)
        reset = menu.addAction("Reset")
        reset.triggered.connect(self._unload_profile)

    def _confirm_discard_profile(self) -> bool:
        """Ask what to do with unsaved changes before switching profiles.

        Returns True when the caller may load or reset, False when it must
        stop. "Save" and "Save As" return True only after a successful save.
        """
        if not self._profile_is_modified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved profile changes")
        box.setText(
            "The current profile has unsaved changes. What should happen to them?"
        )
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        save_as = box.addButton("Save As...", QMessageBox.ButtonRole.ActionRole)
        discard = box.addButton("Ignore", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(discard)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            if self._profile_path is None:
                return self._save_profile() or False
            self._save_current_profile()
            return not self._profile_is_modified()
        if clicked is save_as:
            return bool(self._save_profile())
        return clicked is discard

    def _open_recent_profile(self, path: Path) -> None:
        if not self._confirm_discard_profile():
            return
        try:
            profile = load_profile(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Load profile", str(exc))
            return
        self._apply_profile(profile)
        self._remember_profile_path(path)
        self._baseline_profile = self._profile()
        self._refresh_profile_marker()
        self._append_log(f"Profile loaded: {path}")

    def _save_current_profile(self) -> None:
        if self._profile_path is None:
            answer = QMessageBox.question(
                self,
                "Save profile",
                "No profile is open. Save the current settings as a new profile?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._save_profile()
            return
        state = "Changed" if self._profile_is_modified() else "Unchanged"
        box = QMessageBox(self)
        box.setWindowTitle("Save profile")
        box.setText(
            f"Profile: {self._profile_path.name}\nState: {state}\n\n"
            "Save the current profile settings?"
        )
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is not save:
            return
        try:
            save_profile(self._profile_path, self._profile())
        except OSError as exc:
            QMessageBox.warning(self, "Save profile", str(exc))
            return
        self._remember_profile_path(self._profile_path)
        self._baseline_profile = self._profile()
        self._save_recent_profile()
        self._refresh_profile_marker()
        if not self.comparison.model.stale:
            self._update_filter_summary(stale=False)
        self._append_log(f"Profile saved: {self._profile_path}")

    def _save_profile(self) -> bool:
        default_path = profiles_directory() / "qpy-rsync-profile.json"
        path, _selected = QFileDialog.getSaveFileName(
            self, "Save Profile", str(default_path), "JSON (*.json)"
        )
        if not path:
            return False
        save_profile(Path(path), self._profile())
        self._remember_profile_path(Path(path))
        self._save_recent_profile()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None
        self._refresh_profile_marker()
        if not self.comparison.model.stale:
            self._update_filter_summary(stale=False)
        self._append_log(f"Profile saved: {path}")
        return True

    def _unload_profile(self) -> None:
        if not self._confirm_discard_profile():
            return
        answer = QMessageBox.question(
            self,
            "Unload profile",
            "Reset all profile values to their defaults and forget the recent profile?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        settings = app_settings()
        settings.remove("profile/recent")
        settings.remove("profile/recent_path")
        settings.remove("profile/current_path")
        settings.sync()
        self._profile_path = None
        self.source_edit.clear()
        self.destination_edit.clear()
        index = self.sync_mode.findData(SyncMode.UPDATE)
        if index >= 0:
            self.sync_mode.setCurrentIndex(index)
        self.backup_edit.clear()
        self.protect_backup.setChecked(True)
        self.inventory_after_compare_button.setChecked(False)
        self._backup = BackupOptions(directory="", protect_nested=True)
        self._filters = []
        self._filters_text = ""
        self._update_filter_summary(stale=False)
        self._update_backup_status()
        self._update_external_open_states()
        self._update_command_preview()
        self._update_startup_status()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None
        self._refresh_profile_marker()

    def _load_profile(self) -> None:
        if not self._confirm_discard_profile():
            return
        path, _selected = QFileDialog.getOpenFileName(
            self, "Load Profile", str(profiles_directory()), "JSON (*.json)"
        )
        if not path:
            return
        profile = load_profile(Path(path))
        self._apply_profile(profile)
        self._remember_profile_path(Path(path))
        self._save_recent_profile()
        self._baseline_profile = self._profile()
        self._refresh_profile_marker()
        self._append_log(f"Profile loaded: {path}")

    def _apply_profile(self, profile: SyncProfile) -> None:
        # Loading a profile changes several widgets at once. Letting each
        # `textChanged`/`toggled` signal run does redundant settings.sync()
        # writes and plan invalidation; apply once at the end instead.
        self.source_edit.blockSignals(True)
        self.destination_edit.blockSignals(True)
        self.protect_backup.blockSignals(True)
        self.backup_edit.blockSignals(True)
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
        self._filters_text = profile.filter_text
        self._filters = filter_text_to_rules(self._filters_text)
        self._profile_transfer = deepcopy(profile.transfer)
        self._profile_preservation = deepcopy(profile.preservation)
        self._profile_conflict = profile.conflict_policy
        self.inventory_after_compare_button.blockSignals(True)
        self.inventory_after_compare_button.setChecked(
            profile.inventory_after_compare
        )
        self.inventory_after_compare_button.blockSignals(False)
        self._update_filter_summary(stale=False)
        self._update_backup_status()
        self._update_external_open_states()
        self._update_command_preview()
        self._update_startup_status()
        try:
            self._baseline_profile = self._profile()
        except ValueError:
            self._baseline_profile = None

        self.source_edit.blockSignals(False)
        self.destination_edit.blockSignals(False)
        self.protect_backup.blockSignals(False)
        self.backup_edit.blockSignals(False)
        self._endpoint_text_changed()

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
        self._verified_plan = None
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
        self._refresh_profile_marker()

    def _update_command_preview(self) -> None:
        """Refresh the command preview shown in the progress pane.

        The preview reflects the operation the pointer is over: Compare,
        Verify Decisions, or Synchronize.
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
        """Update the icon and the accessible label of Verify Decisions."""
        self._verify_state = state
        stale = bool(self.comparison.model.stale)
        if state == "verified":
            self.validate_plan_button.setIcon(
                verify_icon(info=True, warning=stale)
            )
            self.validate_plan_button.setAccessibleName("Decisions Verified")
            self.validate_plan_button.setToolTip(
                with_shortcut(
                    "Decisions verified. Verify again to refresh the plan.", "F8"
                )
            )
        elif state == "verifying":
            self.validate_plan_button.setIcon(verify_icon())
            self.validate_plan_button.setAccessibleName("Verifying selected decisions")
            self.validate_plan_button.setToolTip("Verifying selected decisions...")
        else:
            self.validate_plan_button.setIcon(verify_icon(warning=stale))
            self.validate_plan_button.setAccessibleName("Verify Decisions")
            self.validate_plan_button.setToolTip(with_shortcut(_VERIFY_TOOLTIP, "F8"))

    def _invalidate_plan_context(self) -> None:
        self._execution_gate.invalidate()
        self.synchronize_button.setEnabled(False)
        self._current_plan = None
        self._validated_plan = None
        self._verified_plan = None
        self._last_plan_summary = None
        self.validate_plan_button.setEnabled(False)
        self._set_verify_state("idle")

    def _on_decision_changed(self, paths: object) -> None:
        affected = set(paths) if isinstance(paths, (set, list, tuple)) else None
        self._overview_updated("decision", paths=affected)

    def _invalidate_validated_plan(self, *, mark: bool = True) -> None:
        self._validated_plan = None
        self._verified_plan = None
        self.synchronize_button.setEnabled(False)
        self._set_verify_state("idle")
        if mark and self._active_profile is not None and self.comparison.model.changes:
            self._mark_plan_stale()

    @staticmethod
    def _item_contribution(item, included: bool) -> dict[str, int]:
        """The summary deltas of one plan item in the given state."""
        size = int(item.size or 0)
        if included:
            delta = {
                "included": 1,
                "destructive": int(item.destructive),
                "included_size": size,
                "total_size": size
                if item.action
                in {ChangeAction.CREATE, ChangeAction.UPDATE_CONTENT}
                else 0,
                "creates": int(item.action is ChangeAction.CREATE),
                "updates": int(item.action is ChangeAction.UPDATE_CONTENT),
                "metadata": int(item.action is ChangeAction.UPDATE_METADATA),
                "deletions": int(item.action is ChangeAction.DELETE),
                "excluded": 0,
                "retained_destination_only": 0,
            }
        else:
            delta = dict.fromkeys(
                (
                    "included",
                    "destructive",
                    "included_size",
                    "total_size",
                    "creates",
                    "updates",
                    "metadata",
                    "deletions",
                ),
                0,
            )
            if item.comparison_action is ChangeAction.DESTINATION_ONLY:
                delta["retained_destination_only"] = 1
            else:
                delta["excluded"] = 1
        return delta

    def _update_plan_deleted_size(self) -> bool:
        """Refresh only the deleted-size summary after destination metadata."""
        plan = self._current_plan
        if plan is None or not self._plan_paths:
            return False
        metadata = self.comparison.model.destination_metadata()
        if len(self._plan_changes) != len(self.comparison.model.changes):
            return False
        index = build_destination_size_index(metadata)
        delete_paths = {
            item.path
            for item in plan.items
            if item.included and item.action is ChangeAction.DELETE
        }
        total = 0
        for path in delete_paths:
            if any(
                ancestor in delete_paths for ancestor in self._parent_paths(path)
            ):
                continue
            change = self._plan_changes.get(path)
            if change is None:
                return False
            total += destination_subtree_size(path, change.kind, index)
        if total != plan.summary.deleted_size:
            self._current_plan = replace(
                plan, summary=replace(plan.summary, deleted_size=total)
            )
        self._show_plan_summary(log=False)
        return True

    def _apply_plan_changes(
        self, paths: set[str], *, decisions_changed: bool = False
    ) -> bool:
        """Update the cached plan for exclusion/decision changes incrementally."""
        plan = self._current_plan
        if plan is None or not self._plan_items:
            return False
        candidates: set[int] = set()
        for path in paths:
            start = bisect_left(self._plan_paths, path)
            if start < len(self._plan_paths) and self._plan_paths[start] == path:
                candidates.add(start)
            prefix = path + "/"
            index = bisect_left(self._plan_paths, prefix)
            while index < len(self._plan_paths) and self._plan_paths[index].startswith(
                prefix
            ):
                candidates.add(index)
                index += 1
        if not candidates:
            return True
        current_excluded = set(self.comparison.excluded_paths())
        deltas: dict[str, int] = {}
        items = list(plan.items)
        decisions = self.comparison.model.decisions
        for position in candidates:
            path = self._plan_paths[position]
            item_index = self._plan_item_indices[position]
            item = items[item_index]
            change = self._plan_changes.get(path)
            if change is None:
                return False
            excluded = any(
                parent in current_excluded
                for parent in [path, *self._parent_paths(path)]
            )
            included = (
                not excluded
                and decisions.effective(change) is not ChangeDecision.EXCLUDE
            )
            if included == item.included:
                continue
            old = self._item_contribution(item, item.included)
            new = self._item_contribution(item, included)
            for key, value in old.items():
                deltas[key] = deltas.get(key, 0) - value
            for key, value in new.items():
                deltas[key] = deltas.get(key, 0) + value
            items[item_index] = replace(item, included=included)
        fields = {
            key: getattr(plan.summary, key) + value
            for key, value in deltas.items()
            if hasattr(plan.summary, key) and value
        }
        summary = replace(plan.summary, **fields) if fields else plan.summary
        self._current_plan = replace(plan, items=tuple(items), summary=summary)
        self._last_excluded_paths = current_excluded
        if decisions_changed:
            self._last_explicit_decisions = (
                self.comparison.model.decisions.explicit_items()
            )
        return True

    @staticmethod
    def _parent_paths(path: str) -> list[str]:
        parents: list[str] = []
        parent = path.rpartition("/")[0]
        while parent:
            parents.append(parent)
            parent = parent.rpartition("/")[0]
        return parents

    def _decisions_match(self, plan: ExecutionPlan | None) -> bool:
        """Whether today's decisions still describe the given fresh plan."""
        if plan is None or self._active_profile is None:
            return False
        signature = decision_signature(self.comparison.model.decisions)
        if plan.decision_signature != signature:
            return False
        if self._plan_comparison_unchanged:
            # Decision edits never change the comparison itself. Rebuilding a
            # 520k-element identity set here made every undo take seconds.
            profile = self._profile()
            return (
                plan.profile_fingerprint == profile_fingerprint(profile)
                and plan.source_operand == profile.source.rsync_operand()
                and plan.destination_operand == profile.destination.rsync_operand()
            )
        return check_plan_freshness(
            plan,
            self._profile(),
            self.comparison.model.changes,
            signature,
        ).fresh

    def _decisions_match_verified(self) -> bool:
        return self._decisions_match(self._verified_plan)

    def _mark_plan_stale(self) -> None:
        """Mark the plan unverified and update its summary incrementally."""
        if self._current_plan is None:
            return
        current_excluded = set(self.comparison.excluded_paths())
        excluded_change_paths = current_excluded ^ self._last_excluded_paths
        current_decisions = self.comparison.model.decisions.explicit_items()
        before = dict(self._last_explicit_decisions)
        after = dict(current_decisions)
        decision_paths = {
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        }
        changed = bool(excluded_change_paths or decision_paths)
        if changed and self._apply_plan_changes(
            excluded_change_paths | decision_paths,
            decisions_changed=bool(decision_paths),
        ):
            self._show_plan_summary(log=False)
        else:
            # Fall back to a full lightweight estimate only when the cached
            # plan cannot be updated (for example after a new inventory).
            self._stale_summary_timer.start()
        # An immediate undo may bring the decisions back to the state that
        # was verified, or to the state the comparison was made with. In
        # either case the plan is not stale. Only the verified state may
        # re-enable synchronization; a fresh comparison still needs F8.
        reference = self._verified_plan or self._baseline_plan
        if reference is not None and self._decisions_match(reference):
            was_verified = self._verified_plan is not None
            self._validated_plan = self._verified_plan
            self._plan_stale = False
            self.synchronize_button.setEnabled(
                bool(self._current_plan and self._current_plan.summary.included)
            )
            self._set_verify_state("verified" if was_verified else "idle")
            self._refresh_verify_button()
            return
        self._plan_stale = True
        self._validated_plan = None
        # A decision change makes verification invalid, but the patched plan
        # is still safe to review and sync through the confirmation dialog.
        self.synchronize_button.setEnabled(
            bool(self._current_plan and self._current_plan.summary.included)
        )
        self._set_verify_state("idle")
        self._refresh_verify_button()

    def _refresh_estimated_summary(self) -> None:
        if not self._plan_stale:
            return
        with timed("ui.estimated_summary"):
            summary = self._estimated_plan_summary()
        self.overview.set_statistics(summary, estimate=True)
        self.validate_plan_button.setEnabled(summary.included > 0)

    @staticmethod
    def _timed_modified(decisions, changes) -> int:
        with timed("plan.estimated_modified", changes=len(changes)):
            return decisions.modified_count(changes)

    def _estimated_plan_summary(self):
        """ cheap summary from the visible decisions, not an execution plan."""
        from qpy_rsync.core.execution_plan import PlanSummary

        changes = self.comparison.model.changes
        decisions = self.comparison.model.decisions
        with timed("plan.estimated_excluded"):
            excluded = set(self.comparison.excluded_paths())
        # Expand once: checking `path or any ancestor in excluded` for every
        # item used to rebuild the ancestor string chain per change.
        excluded_ancestors = set(excluded)
        for path in excluded:
            parent = path.rpartition("/")[0]
            while parent:
                excluded_ancestors.add(parent)
                parent = parent.rpartition("/")[0]
        # Siblings share the inherited decision; cache it per directory
        # instead of walking the ancestor chain again for every item.
        inherited_cache: dict[str, object] = {}
        missing = object()
        counts = dict.fromkeys(
            ("creates", "updates", "metadata", "deletions", "kept"),
            0,
        )
        included = excluded_count = destructive = 0
        total_size = included_size = deleted_size = 0
        for change in changes:
            action = change.action
            if action in {ChangeAction.NO_CHANGE, ChangeAction.MESSAGE}:
                continue
            path = str(change.path).rstrip("/")
            if path in excluded_ancestors:
                excluded_count += 1
                continue
            parent = path.rpartition("/")[0]
            inherited = inherited_cache.get(parent, missing)
            if inherited is missing:
                inherited = decisions.inherited(parent)
                inherited_cache[parent] = inherited
            selected = inherited is not ChangeDecision.EXCLUDE
            if not selected:
                if action is ChangeAction.DESTINATION_ONLY:
                    counts["kept"] += 1
                else:
                    excluded_count += 1
                continue
            included += 1
            size = int(change.size or 0)
            included_size += size
            if action in {ChangeAction.CREATE, ChangeAction.UPDATE_CONTENT}:
                total_size += size
            if action is ChangeAction.CREATE:
                counts["creates"] += 1
            elif action is ChangeAction.UPDATE_CONTENT:
                counts["updates"] += 1
            elif action is ChangeAction.UPDATE_METADATA:
                counts["metadata"] += 1
            elif action is ChangeAction.DELETE:
                counts["deletions"] += 1
                destructive += 1
                deleted_size += int(
                    self.comparison.model._destination_size(change) or 0
                )
        return PlanSummary(
            included=included,
            excluded=excluded_count,
            modified=_timed_modified(decisions, changes),
            retained_destination_only=counts["kept"],
            destructive=destructive,
            creates=counts["creates"],
            updates=counts["updates"],
            metadata=counts["metadata"],
            deletions=counts["deletions"],
            deleted_size=deleted_size,
            backup_enabled=bool(
                self._profile().backup.enabled if self._active_profile else False
            ),
            total_size=total_size,
            included_size=included_size,
        )

    def _refresh_verify_button(self) -> None:
        # A decision edit makes the plan stale even though the comparison is
        # still fresh. Show that with the same small badge the other buttons
        # use, never by painting the whole background.
        warning = self._plan_stale or self.comparison.model.stale
        self.validate_plan_button.setIcon(
            verify_icon(info=not warning and self._verify_state == "verified", warning=warning)
        )
        self.validate_plan_button.setToolTip(
            "Plan changed — press Verify Decisions to rebuild and verify."
            if self._plan_stale
            else "Verify Decisions"
        )

    def _refresh_plan_summary(self) -> None:
        if self._skip_next_plan_rebuild:
            self._skip_next_plan_rebuild = False
            return
        with timed("ui.plan_rebuild"):
            self._rebuild_plan_summary()

    def _rebuild_plan_summary(self) -> None:
        if self._active_profile is None:
            self._current_plan = None
            self._plan_paths = []
            self._plan_item_indices = []
            self._plan_items = {}
            self._plan_changes = {}
            self._last_excluded_paths = set()
            self._last_plan_summary = None
            self.overview.set_statistics(None)
            self.validate_plan_button.setEnabled(False)
            return
        self._update_excluded_count()
        with timed("plan.build", changes=len(self.comparison.model.changes)):
            self._current_plan = build_execution_plan(
                self._active_profile,
                self.comparison.model.changes,
                self.comparison.model.decisions,
                self.comparison.model.destination_metadata(),
            )
        with timed("plan.post_index", items=len(self._current_plan.items)):
            entries = sorted(
                (item.path, index)
                for index, item in enumerate(self._current_plan.items)
            )
            self._plan_paths = [path for path, _index in entries]
            self._plan_item_indices = [index for _path, index in entries]
            self._plan_items = {
                item.path: item for item in self._current_plan.items
            }
            self._plan_changes = {
                str(change.path).rstrip("/"): change
                for change in self.comparison.model.changes
            }
        with timed("plan.state_snapshot"):
            self._last_excluded_paths = set(self.comparison.excluded_paths())
            self._last_explicit_decisions = (
                self.comparison.model.decisions.explicit_items()
            )
            self._plan_comparison_unchanged = True
            self._plan_exec_hint = self._executable_hint(
                self.comparison.model.changes
            )
        self._plan_stale = False
        self._stale_summary_timer.stop()
        self._refresh_verify_button()
        self._show_plan_summary()

    def _show_plan_summary(self, *, log: bool = True) -> None:
        plan = self._current_plan
        if plan is None:
            return
        summary = plan.summary
        noun = "item" if summary.included == 1 else "items"
        text = (
            f"Selected: {summary.included} {noun}, "
            f"{format_size(summary.total_size)}; "
            f"new {summary.creates}, updated {summary.updates}, "
            f"metadata {summary.metadata}, "
            f"deleted {summary.deletions}; "
            f"kept {summary.retained_destination_only}, unchecked {summary.excluded}, "
            f"modified {summary.modified}, destructive {summary.destructive}; "
            f"backup {'on' if summary.backup_enabled else 'off'}"
        )
        if log and text != self._last_plan_summary:
            self._last_plan_summary = text
            self._append_log(text)
        self.overview.set_statistics(summary)
        self.validate_plan_button.setEnabled(summary.included > 0)
        self.synchronize_button.setEnabled(summary.included > 0)
        self._execution_gate.selection_changed(included=summary.included)

    def _validate_selected_plan(self) -> None:
        self._backup_changed()
        if self._plan_stale:
            with timed("verify.plan_rebuild"):
                self._refresh_plan_summary()
        if self._current_plan is None or self._active_profile is None:
            return
        signature = decision_signature(self.comparison.model.decisions)
        freshness = check_plan_freshness(
            self._current_plan,
            self._profile(),
            self.comparison.model.changes,
            signature,
        )
        if not freshness.fresh:
            self._validated_plan = None
            self._verified_plan = None
            QMessageBox.warning(
                self,
                "Execution plan is stale",
                "Plan validation is blocked: " + "; ".join(freshness.reasons),
            )
            return
        if self._verification_enabled and self._verification_rsync:
            # Advanced opt-in: compare rsync's live view with the reviewed
            # plan. Mismatches are warnings, handled in _plan_validation_finished.
            self._plan_validation.validate(self._active_profile, self._current_plan)
            return
        # Verify against the comparison the user actually reviewed. A second
        # rsync dry run would re-scan the live tree and report unrelated
        # changes (browser profiles, caches) as mismatches. The plan and the
        # comparison come from the same snapshot, and the decisions are
        # path-based, so checking them locally is both exact and stable.
        self._plan_validation_started()
        mismatch = compare_plan_to_changes(
            self._current_plan,
            self.comparison.model.changes,
            self.comparison.model.decisions,
        )
        self._append_log(
            "Verification used the existing comparison; no second rsync run."
        )
        self._append_log("STATE verification-reused-comparison")
        self._plan_validation_finished(
            PlanValidationResult(mismatch.valid, mismatch, "", 0)
        )

    def _plan_validation_started(self) -> None:
        self._start_rsync_clock("verification")
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
        self.progress_label.setText("Verifying selected decisions...")
        self._set_state("Verifying selected decisions...")
        self._append_log("STATE verifying-selected-actions")

    def _plan_validation_finished(self, result: PlanValidationResult) -> None:
        if self._closing:
            return
        self._log_rsync_elapsed("verification")
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self.validate_plan_button.setEnabled(True)
        self._set_verify_state("idle")
        if result.valid:
            self._validated_plan = self._current_plan
            self._verified_plan = self._current_plan
            self._execution_gate.verification_succeeded()
            self.synchronize_button.setEnabled(True)
            self._set_verify_state("verified")
            if self._current_plan is not None:
                summary = self._current_plan.summary
                noun = "item" if summary.included == 1 else "items"
                self._append_log(
                    "Decisions verified, selected: "
                    f"new {summary.creates}, updated {summary.updates}, "
                    f"metadata {summary.metadata}, "
                    f"deleted {summary.deletions}; "
                    f"{summary.included} {noun}, {format_size(summary.total_size)}"
                )
            self.progress_bar.setValue(100)
            self.progress_label.setText("Selected decisions verified")
            self._set_state("Selected decisions verified.", "success")
            self._append_log("STATE decisions-verified")
            self._end_bulk_logging()
            return
        self._validated_plan = None
        self._verified_plan = None
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
        # A live tree can produce thousands of mismatches. Keep the dialog
        # bounded: the detail area scrolls and the buttons stay reachable.
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Verification mismatch")
        box.setText(
            "The second rsync run saw a different set of changes than the "
            "comparison you reviewed. This is expected on a live directory "
            "that changes between the two runs. Synchronization is not "
            "blocked; review before continuing."
        )
        box.setInformativeText(
            f"{len(result.mismatch.missing)} missing, "
            f"{len(result.mismatch.unexpected)} unexpected item(s).\n\n"
            "Re-compare close to verification to reduce the difference, or "
            "disable the rsync check in Settings > Advanced if the live "
            "tree changes too often."
        )
        if detail:
            box.setDetailedText(detail)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        for line in detail.splitlines()[:50]:
            self._append_log(line, severity="error")
        if len(detail.splitlines()) > 50:
            self._append_log("... further mismatches omitted from the journal", severity="error")
        box.exec()
        self._set_state("Verification found a mismatch.", "warning")

    def _plan_validation_cancelled(self) -> None:
        if self._closing:
            return
        self._log_rsync_elapsed("verification")
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self._validated_plan = None
        self._verified_plan = None
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
        self._log_rsync_elapsed("verification")
        self.cancel_button.setEnabled(False)
        self._validated_plan = None
        self._verified_plan = None
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
        # The backup settings and the plan are checked before the dialog
        # opens, which can take a moment on a large comparison. Show that
        # the button was heard and let the interface repaint.
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("Preparing the synchronization...")
        self._set_state("Preparing the synchronization...")
        QApplication.processEvents()
        self._backup_changed()
        QApplication.processEvents()
        plan = self._validated_plan or self._current_plan
        if (
            plan is None
            or self._active_profile is None
            or self._execution_gate.state
            not in (ExecutionGateState.SELECTION_READY, ExecutionGateState.VERIFIED)
        ):
            QMessageBox.warning(
                self,
                "No selected actions",
                "Compare the locations and select at least one action first.",
            )
            return
        with timed("plan.freshness_check", changes=len(self.comparison.model.changes)):
            freshness = check_plan_freshness(
                plan,
                self._profile(),
                self.comparison.model.changes,
            )
        self.progress_label.setText("Preparing the synchronization...")
        QApplication.processEvents()
        if not freshness.fresh:
            self._invalidate_validated_plan()
            QMessageBox.warning(
                self,
                "Selected actions are out of date",
                "Compare again: " + "; ".join(freshness.reasons),
            )
            return
        self._execution_gate.confirmation_opened()
        self._cleanup_dialog_filter()
        filter_context = temporary_decision_filter(plan)
        filter_path = filter_context.__enter__()
        self._dialog_filter_context = filter_context
        started = False
        try:
            dialog = SyncConfirmationDialog(
                self._active_profile,
                plan,
                self,
                filter_path=filter_path,
                verified=self._validated_plan is not None,
            )
            accepted = bool(dialog.exec())
            if not accepted:
                self._execution_gate.confirmation_cancelled()
                self.synchronize_button.setEnabled(True)
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
                self.progress_label.setText("Synchronization cancelled.")
                self._set_state("Synchronization cancelled.", "warning")
                return
            try:
                self._sync_service.synchronize(
                    self._active_profile,
                    plan,
                    filter_path=filter_path,
                )
                started = True
            except ValueError as exc:
                self._execution_gate.confirmation_cancelled()
                self.synchronize_button.setEnabled(True)
                self._set_state("Synchronization blocked.", "error")
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
        self._start_rsync_clock("synchronization")
        self._begin_bulk_logging()
        self._set_hovered_action("synchronize")
        self._execution_gate.execution_started()
        self._set_busy_controls(True)
        self.comparison.set_stale(True, block_views=True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
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
        self._log_rsync_elapsed("synchronization")
        self.progress_bar.setValue(100)
        self.progress_label.setText("Synchronization completed")
        self._execution_gate.execution_completed()
        self._append_log(
            f"STATE synchronization-completed exit_code={result.exit_code}"
        )
        self._end_bulk_logging()
        self._set_busy_controls(False)
        self._validated_plan = None
        self._verified_plan = None
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
        self._log_rsync_elapsed("synchronization")
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
        self.comparison.set_stale(True, block_views=True)
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
        if not self.preserve_button.isChecked():
            answer = QMessageBox.warning(
                self,
                "Fresh comparison",
                "Preserve decisions is off. This comparison will discard all "
                "manual include and exclude decisions. Check the box to keep "
                "them, or continue to start fresh.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Ok:
                return
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
        from qpy_rsync.backend.process_runner import ProcessState

        self._compare_generation += 1
        if self._service.state in (ProcessState.STARTING, ProcessState.RUNNING):
            self._service.cancel()
        self._active_profile = profile
        self._comparison_profile = profile
        self._prepare_decision_preservation(profile)
        self._append_log("$ " + shlex.join(spec.argv()))
        self._service.compare(profile)

    def _comparison_sorted(self, column: int, order: object) -> None:
        """Report the new order of the comparison."""
        labels = {
            0: "Item",
            1: "Items",
            2: "Size",
            3: "Modified",
            4: "Decisions",
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

    def _overview_updated(
        self, kind: str = "new", paths: set[str] | None = None
    ) -> None:
        """Refresh the overview with the items the filters show."""
        root_name = ""
        if self._active_profile is not None:
            root_name = self._active_profile.source.path.rstrip("/").rsplit("/", 1)[-1]
        with timed("ui.overview_update"):
            # The comparison model collected these totals during its own
            # filter pass, so the overview never rescans the whole list.
            if kind == "new":
                self.overview.set_paths(
                    self.comparison.model.all_folder_paths(), root_name
                )
            self.overview.set_aggregates(
                self.comparison.model.overview_aggregates(), root_name
            )
            self._update_excluded_count()
        if kind == "display":
            return
        if kind == "new":
            self._refresh_plan_summary()
            self._baseline_plan = self._current_plan
            return
        self._mark_plan_stale()

    def _overview_folder_activated(self, path: str) -> None:
        """Select a folder of the overview in the tree panes."""
        if self._hybrid_view is not None:
            self._hybrid_view.select_path(path, focus=True)
        else:
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
        configured = self._diff_command.strip()
        if configured:
            try:
                shlex.split(configured)
            except ValueError as exc:
                self._set_state("Diff tool unavailable", "error")
                self._set_status(
                    f"The diff tool command cannot be parsed: {exc}", "error"
                )
                QMessageBox.information(
                    self, "Diff tool unavailable", f"The command cannot be parsed: {exc}"
                )
                return
        try:
            request = build_diff_request(
                self._active_profile,  # type: ignore[arg-type]
                change,
                tool=(
                    DiffTool(name="diff", executable=shlex.split(configured)[0])
                    if configured
                    else None
                ),
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
        if configured:
            # The command of the user decides where the two files go.
            context = ToolContext(
                picked_full_path=str(request.source),
                picked_directory=str(request.source.parent),
                picked_name=request.source.name,
                other_full_path=str(request.destination),
                other_directory=str(request.destination.parent),
                other_name=request.destination.name,
                picked_endpoint=self._active_profile.source,  # type: ignore[attr-defined]
                other_endpoint=self._active_profile.destination,  # type: ignore[attr-defined]
                tool_name="diff",
            )
            try:
                argv = build_tool_command(
                    ExternalTool(name="diff", command=configured), context
                )
            except ExternalToolError as exc:
                self._set_state("Diff tool unavailable", "error")
                self._set_status(str(exc), "error")
                QMessageBox.information(self, "Diff tool unavailable", str(exc))
                return
            executable = argv[0]
            arguments = argv[1:]
        else:
            executable = request.tool.executable
            arguments = [str(request.source), str(request.destination)]
        started, _pid = QProcess.startDetached(executable, arguments)
        if not started:
            self._set_state("Diff tool could not start", "error")
            self._set_status(f"Could not start {executable}.", "error")
            QMessageBox.warning(self, "Could not start diff tool", executable)
            return
        self._append_log("$ " + shlex.join([executable, *arguments]))
        self._set_state(
            f"Opened {path} in {request.tool.name}.",  # type: ignore[attr-defined]
            "success",
        )

    def _run_external_tool(
        self, name: str, path: str, side: str, is_directory: bool
    ) -> None:
        """Run one of the tools the user configured on an item."""
        tool = next(
            (tool for tool in self._external_tools if tool.name == name), None
        )
        if tool is None:
            return
        profile = self._active_profile
        if profile is None:
            self._set_status("No profile is loaded.", "error")
            return
        picked = profile.source if side == "source" else profile.destination
        other = profile.destination if side == "source" else profile.source
        context = item_context(
            path,
            is_directory=is_directory,
            picked_root=picked.path,
            other_root=other.path,
            picked_endpoint=picked,
            other_endpoint=other,
            tool_name=tool.name,
            options=tool.options,
        )
        try:
            argv = build_tool_command(tool, context)
        except ExternalToolError as exc:
            self._set_status(str(exc), "error")
            self._set_state("The tool command cannot be used", "error")
            return
        self._append_log("$ " + shlex.join(argv))
        # The tool starts in the folder of the item, when that folder is on
        # this machine.
        working_directory = context.picked_directory
        if working_directory and not Path(working_directory).is_dir():
            working_directory = ""
        try:
            subprocess.Popen(
                argv,
                cwd=working_directory or None,
                start_new_session=True,
            )
        except OSError as exc:
            self._set_status(f"Could not start {tool.name}: {exc}", "error")
            self._set_state(f"{tool.name} could not start", "error")
            return
        self._set_state(f"Started {tool.name}.", "success")

    def _comparison_started(self) -> None:
        self._comparison_announced = False
        self._active_compare_generation = self._compare_generation
        self._start_rsync_clock("dry run")
        self._begin_bulk_logging()
        self._set_hovered_action("compare")
        self._inventory_service.cancel()
        self._inventory_token = 0
        self._inventory_pending_key = None
        # The metadata of the previous comparison no longer describes the
        # destination.
        self.comparison.set_destination_metadata({})
        # Exclusions and folds only live in memory, so a new comparison
        # starts with an empty exclusion and every folder open.
        exclusion = getattr(self.comparison.model, "exclusion", None)
        if exclusion is not None:
            exclusion.clear()
        self.comparison.clear_collapsed()
        self.action_filters.set_excluded_count(0)
        self.compare_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.pause_button.setEnabled(True)
        self._reset_pause_button()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Comparing...")
        self._set_state("Comparing...")
        self._append_log("STATE comparing")

    def _comparison_items(self, count: int) -> None:
        """Report how many items the dry run has found so far."""
        if self._closing:
            return
        self.progress_label.setText(f"Comparing... {count:,} item(s) found")

    def _comparison_progress(self, _progress: object) -> None:
        # rsync's incremental counter has no stable total for a dry run. Its
        # values can fall when rsync revises the total, so it must not drive
        # the visible count: _comparison_items owns that label and uses the
        # monotonically growing number of parsed changes.
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)

    def _comparison_cancelled(self) -> None:
        if self._closing:
            return
        self._log_rsync_elapsed("dry run")
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
        if self._active_compare_generation != self._compare_generation:
            # A newer Compare was started while this one was finishing.
            return
        self._set_cached_destination(None)
        self._inventory_service.set_cached_source(None)
        self._cached_source_paths = None
        self._showing_unchanged = False
        self._last_phase_started = time.monotonic()
        self._log_rsync_elapsed("dry run")
        self._save_recent_profile()
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._reset_pause_button()
        self.progress_bar.setValue(100)
        self.progress_label.setText("Comparison completed")
        self._last_changed_changes = list(result.parsed.changes)
        self.comparison.model.preserve_decisions = getattr(
            self, "_preserve_for_compare", self._preserve_decisions
        )
        self.comparison.model.detect_inherited_conflicts = (
            self._detect_inherited_conflicts
        )
        if getattr(self, "_preserve_reason", ""):
            self._append_log(
                f"Decisions reset for this comparison: {self._preserve_reason}."
            )
        elif getattr(self, "_preserve_for_compare", False):
            self._append_log("Decisions preserved for this comparison.")
        self._last_compare_locations = getattr(
            self, "_next_compare_locations", self._last_compare_locations
        )
        self._last_compare_filters = getattr(
            self, "_next_compare_filters", self._last_compare_filters
        )
        self.comparison.source_root = self._active_profile.source.path.rstrip("/")
        self.comparison.destination_root = self._active_profile.destination.path.rstrip("/")
        self.comparison.source_is_local = (
            self._active_profile.source.kind is EndpointKind.LOCAL
        )
        self.comparison.destination_is_local = (
            self._active_profile.destination.kind is EndpointKind.LOCAL
        )
        view_started = time.monotonic()
        metadata_started = self._fetch_destination_metadata()
        self._apply_inventory_after_compare()
        self._append_log(
            f"Comparison view built in {time.monotonic() - view_started:.2f} s."
        )
        discarded = self.comparison.model.discarded_decisions
        conflicts = self.comparison.model.conflicts()
        if discarded or conflicts:
            self._append_log(
                f"{discarded} decision(s) dropped; "
                f"{len(conflicts)} still on the list need review."
            )
            self._set_status(
                "Some decisions no longer apply — review the highlighted items.",
                "warning",
            )
        self.comparison.set_stale(False)
        if self._preserve_before_force is not None:
            restore = self._preserve_before_force
            self._preserve_before_force = None
            self._set_preserve_checked(restore)
            self._preserve_decisions = restore
            self.comparison.model.preserve_decisions = restore
            settings = app_settings()
            settings.setValue("decisions/preserve", restore)
            settings.sync()
            self._append_log(
                "Preserve decisions restored after the fresh comparison."
            )
        self._update_filter_summary(stale=False)
        self._set_locations_stale(False)
        self._validated_plan = None
        self._verified_plan = None
        # comparison.set_changes() below emits changes_updated and rebuilds
        # the plan; avoid a second full rebuild here.
        for message in result.parsed.diagnostics:
            self._append_log(message)
        self._last_compare_count = len(result.parsed.changes)
        if metadata_started:
            self._metadata_pending = True
            self._metadata_watchdog.start()
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("Gathering destination metadata...")
        else:
            self._finish_comparison_status()
        # The beep and the "complete" state are announced by
        # _finish_comparison_status(), which runs only after the destination
        # metadata listing has finished (or failed/timed out).


    def _add_shortcut(self, key: str, slot) -> None:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.activated.connect(lambda: slot())

    def _focus_compare_pane(self, tree) -> None:
        """Focus a compare pane with a valid current item.

        A QTableView that has never been clicked has no current index. Giving
        it focus alone leaves arrow keys and further shortcuts inert, and the
        first arrow press only parks the cursor on row zero without a real
        selection. Set the current item explicitly first.
        """
        if not tree.currentIndex().isValid() and tree.model().rowCount() > 0:
            from PySide6.QtCore import QItemSelectionModel

            index = tree.model().index(0, 0)
            tree.selectionModel().setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            tree.scrollTo(index)
        tree.setFocus()

    def _native_pane_widgets(self) -> tuple | None:
        """The native Source, Action and Destination views, left to right."""
        if self._hybrid_view is None:
            return None
        from PySide6.QtWidgets import QTableView

        tables = sorted(
            self._hybrid_view.widget.findChildren(QTableView),
            key=lambda table: table.x(),
        )
        if len(tables) < 3:
            return None
        return tables[0], tables[1], tables[2]

    def _focus_named_pane(self, name: str) -> None:
        """Focus a comparison pane in whichever view is active."""
        if name == "overview":
            if self._hybrid_view is not None:
                widget = self.overview
            else:
                widget = self.overview.tree
            widget.setFocus()
            return
        native = self._native_pane_widgets()
        if native is not None:
            widget = {"source": native[0], "action": native[1],
                      "destination": native[2]}[name]
        else:
            widget = {
                "source": self.comparison.source,
                "action": self.comparison.action,
                "destination": self.comparison.destination,
            }[name]
        self._focus_compare_pane(widget)

    def _install_navigation_shortcuts(self) -> None:
        panes = {
            self.comparison.source,
            self.comparison.destination,
            self.comparison.action,
            self.overview.tree,
        }
        for key, widget in (
            ("Alt+S", self.source_edit),
            ("Alt+D", self.destination_edit),
        ):
            self._add_shortcut(
                key,
                lambda w=widget: (
                    self._focus_compare_pane(w) if w in panes else w.setFocus()
                ),
            )
            if hasattr(widget, "setToolTip"):
                widget.setToolTip(
                    f"{widget.toolTip()} (Shortcut: {key}) (Esc ends editing)"
                )
        for key, name in (
            ("Ctrl+W", "overview"),
            ("Ctrl+S", "source"),
            ("Ctrl+D", "destination"),
            ("Ctrl+N", "action"),
        ):
            self._add_shortcut(key, lambda n=name: self._focus_named_pane(n))
        for number in range(1, 9):
            self._add_shortcut(
                f"Alt+{number}",
                lambda n=number: self.action_filters.toggle_shortcut(n),
            )
            self._add_shortcut(
                f"Ctrl+{number}",
                lambda n=number: self.action_filters.toggle_shortcut(n, inverted=True),
            )
        for key, button in (
            ("Ctrl+B", self.backup_open),
            ("Ctrl+L", self.log_file_open),
        ):
            self._add_shortcut(key, button.click)
            button.setToolTip(f"{button.toolTip()} (Shortcut: {key})")
        self._add_shortcut("Alt+Return", self._open_current_context_menu)
        self._add_shortcut("Ctrl+T", self._open_current_context_menu)
        for edit in (self.source_edit, self.destination_edit):
            edit.installEventFilter(self)

    def _open_current_context_menu(self) -> None:
        from PySide6.QtWidgets import QApplication

        widget = QApplication.focusWidget()
        native = self._native_pane_widgets()
        if native is not None:
            for pane, tree in enumerate(native):
                if widget is tree or tree.isAncestorOf(widget):
                    row = tree.currentIndex().row()
                    path = self._hybrid_view.path_of_row(row)
                    rect = tree.visualRect(tree.currentIndex())
                    point = rect.center()
                    global_point = tree.viewport().mapToGlobal(point)
                    self._native_context_menu(
                        pane, path, global_point.x(), global_point.y()
                    )
                    return
            return
        for tree in (
            self.comparison.source,
            self.comparison.action,
            self.comparison.destination,
        ):
            if widget is tree or tree.isAncestorOf(widget):
                self.comparison.show_context_menu_for_current(tree)
                return

    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        try:
            if event is None:
                return super().eventFilter(watched, event)
            if event.type() == QEvent.Type.Enter:
                action = watched.property("previewAction") if hasattr(watched, "property") else None
                if action:
                    self._set_hovered_action(str(action))
            if (
                event.type() == QEvent.Type.KeyPress
                and watched in (self.source_edit, self.destination_edit)
                and int(event.key()) == int(Qt.Key.Key_Escape)
            ):
                # End editing without consuming the key, so the main window's
                # shortcuts work again on the next press.
                watched.clearFocus()
                return True
        except RuntimeError:
            # Qt may already have destroyed the watched widget during shutdown.
            return False
        return super().eventFilter(watched, event)

    def _filter_directories_changed(self, checked: bool) -> None:
        settings = app_settings()
        settings.setValue("comparison/filter-directories", bool(checked))
        settings.sync()
        self.comparison.set_filter_directories(checked)

    def _apply_action_filters(self, actions: object) -> None:
        selected = actions if isinstance(actions, set) else None
        self.comparison.set_action_filter(self._actions_with_unchanged(selected))

    def _actions_with_unchanged(
        self, actions: set[ChangeAction] | None
    ) -> set[ChangeAction] | None:
        """The action filter, with the unchanged items when they are shown.

        The unchanged items are not one of the action checkboxes, so the
        toggle that shows them has to allow them explicitly; otherwise they
        would disappear as soon as an action checkbox is used.
        """
        if actions is None:
            return None
        if self.show_unchanged.isChecked():
            return set(actions) | {ChangeAction.NO_CHANGE}
        return set(actions)

    def _apply_show_excluded(self, show: bool) -> None:
        """Show the excluded items, or hide them again."""
        self.comparison.set_show_excluded(show)
        if self._hybrid_view is not None:
            self._hybrid_view.set_show_excluded(show)
        total = self.comparison.model.exclusions.count()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        if show:
            self.progress_label.setText(
                f"Showing {total:,} excluded item(s); they are dimmed."
            )
            self._append_log(
                f"Showing {total:,} excluded item(s).", severity="info"
            )
        else:
            self.progress_label.setText(
                f"{total:,} excluded item(s) are hidden again."
                if total
                else "No items are excluded."
            )
            self._append_log(
                f"Hiding {total:,} excluded item(s) again.", severity="info"
            )

    def _reset_exclusions(self) -> None:
        """Reset every exclusion and report it."""
        count = self.comparison.model.exclusions.count()
        if not count:
            self.progress_label.setText("No items are excluded.")
            return
        self.comparison.reset_exclusions()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(
            f"All {count:,} exclusion(s) are reset."
        )
        self._append_log(f"Reset {count:,} exclusion(s).", severity="info")

    def _exclude_path(self, path: str) -> None:
        """Exclude a folder or an item from the comparison."""
        if not hasattr(self.comparison, "exclude_path"):
            return
        self.comparison.exclude_path(path)
        self.action_filters.set_excluded_count(
            self.comparison.model.exclusion.count()
        )

    def _restore_path(self, path: str) -> None:
        """Restore a excluded folder or item."""
        if not hasattr(self.comparison, "restore_path"):
            return
        self.comparison.restore_path(path)
        self.action_filters.set_excluded_count(
            self.comparison.model.exclusion.count()
        )

    def _update_excluded_count(self) -> None:
        """Keep the excluded item count next to the toggle up to date."""
        exclusion = getattr(self.comparison.model, "exclusion", None)
        count = exclusion.count() if exclusion is not None else 0
        self.action_filters.set_excluded_count(count)

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
        # stay hidden until the user asks for them. A fresh comparison must
        # always feed the model: its previous change list belongs to another
        # profile and cannot be skipped just because it is non-empty.
        self._set_comparison_changes(changed)
        self._start_inventory(key, changed)

    def _apply_inventory_mode(self) -> None:
        """Show or hide the unchanged items of the current comparison.

        Showing the unchanged items runs the inventory for this comparison;
        it must not silently switch the persistent "inventory after compare"
        button on — that setting belongs to the user.
        """
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
            # A fresh comparison or a transition out of Show-unchanged must
            # feed the model. Native handoff skips identical path sets, so the
            # expensive Qt rebuild is already avoided in hybrid mode.
            self._set_comparison_changes(changed)
            self._showing_unchanged = False
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
        self._set_comparison_changes(changed)
        self._start_inventory(key, changed)

    def _hide_unchanged(self, changed: list[object]) -> None:
        self.show_unchanged.blockSignals(True)
        self.show_unchanged.setChecked(False)
        self.show_unchanged.blockSignals(False)
        self.progress_label.setText("Unchanged items hidden")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._set_comparison_changes(changed)
        self._showing_unchanged = False

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
            # The filter is set before the rows are built, so the unchanged
            # items are shown right away.
            self.comparison.set_action_filter(
                set(self.action_filters.visible_actions())
                | {ChangeAction.NO_CHANGE},
                apply=False,
            )
            self._set_comparison_changes(changes)
        finally:
            QApplication.restoreOverrideCursor()
        self._showing_unchanged = True
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(self._inventory_summary(unchanged))

    def _inventory_summary(self, unchanged: int) -> str:
        return f"Showing {unchanged:,} unchanged item(s)."

    def _has_cached_destination(self) -> bool:
        getter = getattr(
            self._inventory_service, "has_cached_destination", None
        )
        return bool(getter()) if getter is not None else False

    @staticmethod
    def _executable_hint(changes) -> tuple:
        """Cheap identity check for an unchanged-only transition."""
        executable = [
            change for change in changes
            if change.action not in (ChangeAction.NO_CHANGE, ChangeAction.MESSAGE)
        ]
        if not executable:
            return (0, "", "")
        return (
            len(executable),
            str(executable[0].path).rstrip("/"),
            str(executable[-1].path).rstrip("/"),
        )

    def _set_comparison_changes(self, changes) -> None:
        """Feed the Python model, skipping row/filter work in native mode."""
        # Never skip a new handoff just because a cheap signature matches:
        # two profiles can produce the same first/last paths while differing
        # in the middle, which used to leave the new comparison stale.
        self._plan_comparison_unchanged = False
        unchanged_only = False
        if self._current_plan is not None:
            if self._executable_hint(changes) == self._plan_exec_hint:
                # Adding/removing unchanged items changes neither the plan
                # nor any decision, so skip both rebuilds.
                unchanged_only = True
                self._skip_next_plan_rebuild = True
        with timed(
            "ui.model_set_changes",
            changes=len(changes),
            skip_view=self._hybrid_view is not None,
            skip_reconcile=unchanged_only,
        ):
            self.comparison.set_changes(
                changes,
                skip_view=self._hybrid_view is not None,
                skip_directories=self._hybrid_view is not None,
                skip_reconcile=unchanged_only,
            )
        if self._hybrid_view is not None:
            if unchanged_only and len(changes) < len(self._hybrid_view._handed_paths or ()):
                self._hybrid_view.set_changes_for_unchanged(len(changes))
                return
            import os

            source = self.source_edit.text().rstrip("/")
            destination = self.destination_edit.text().rstrip("/")
            self._hybrid_view.set_root_names(
                os.path.basename(source) or "Source",
                os.path.basename(destination) or "Destination",
            )
            with timed("ui.native_handoff", changes=len(changes)):
                self._hybrid_view.set_changes(changes)

    def _enable_hybrid_view(self) -> None:
        """Replace the comparison panes with native Qt models (opt-in)."""
        from qpy_rsync.gui.native_hybrid_view import (
            NativeHybridView,
            NativeOverviewShim,
        )

        try:
            view = NativeHybridView()
        except (RuntimeError, ImportError, OSError):
            return
        self._hybrid_view = view
        self._hybrid_selected_path = ""
        self._python_overview = self.overview
        shim = NativeOverviewShim(view.overview_widget)
        index = self.log_splitter.indexOf(self.overview)
        if index >= 0:
            self.log_splitter.replaceWidget(index, shim)
        self.overview = shim
        shim.folder_activated.connect(self._overview_folder_activated)
        shim.exclusion_requested.connect(self._exclude_path)
        shim.restore_requested.connect(self._restore_path)
        shim.filter_requested.connect(self._add_filter_phrase)
        view.on_decision_changed(self._on_native_decision)
        view.on_selection_changed(self._on_native_selection)
        view.on_context_menu(self._native_context_menu)
        view.on_header_context_menu(self._native_header_menu)
        self._route_controls_to_native(view)
        index = self.main_splitter.indexOf(self.comparison)
        if index >= 0:
            self.main_splitter.replaceWidget(index, view.widget)
        self.comparison.hide()
        # A live enable after a finished Compare must hand the current dataset
        # to native; otherwise the native panes are empty until the next run.
        if self._last_changed_changes:
            import os

            source = self.source_edit.text().rstrip("/")
            destination = self.destination_edit.text().rstrip("/")
            view.set_root_names(
                os.path.basename(source) or "Source",
                os.path.basename(destination) or "Destination",
            )
            view.set_changes(list(self._last_changed_changes))
            self._sync_native_decisions()
            metadata = self.comparison.model.destination_metadata()
            if metadata:
                view.set_destination_metadata(dict(metadata))
            view.set_action_filter(self.action_filters.visible_actions())
            for folder in self.comparison.model.collapsed:
                view.set_collapsed(folder, True)
            if self._hybrid_selected_path:
                view.select_path(self._hybrid_selected_path)

    def _disable_hybrid_view(self) -> None:
        """Restore the Python comparison and overview after disabling hybrid."""
        view = self._hybrid_view
        if view is None:
            return
        for obj, name, original in self._hybrid_originals.values():
            if original is None:
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass
            else:
                setattr(obj, name, original)
        self._hybrid_originals.clear()
        self.undo_decision_action.triggered.disconnect()
        self.undo_decision_action.triggered.connect(self._hybrid_undo_original)
        self.redo_decision_action.triggered.disconnect()
        self.redo_decision_action.triggered.connect(self._hybrid_redo_original)
        index = self.log_splitter.indexOf(self.overview)
        if index >= 0:
            self.log_splitter.replaceWidget(index, self._python_overview)
        self.overview = self._python_overview
        index = self.main_splitter.indexOf(view.widget)
        if index >= 0:
            self.main_splitter.replaceWidget(index, self.comparison)
        self.comparison.show()
        view.shutdown()
        self._hybrid_view = None
        if self._last_changed_changes:
            # Rebuilding the Python model/view is the expensive operation the
            # native view exists to avoid (12-23 s at 520k items). Let the
            # settings dialog close and paint a status first, then do it.
            self._set_state("Rebuilding the Python comparison view...")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QTimer.singleShot(0, self._finish_disable_hybrid_view)

    def _finish_disable_hybrid_view(self) -> None:
        try:
            if self._closing or self._hybrid_view is not None:
                return
            if self._last_changed_changes:
                self.comparison.set_changes(list(self._last_changed_changes))
        finally:
            QApplication.restoreOverrideCursor()
            self._update_startup_status()

    def _patch_for_hybrid(self, obj: object, name: str, value: object) -> None:
        """Remember a monkey-patched method so disabling hybrid restores it."""
        key = (id(obj), name)
        if key not in self._hybrid_originals:
            self._hybrid_originals[key] = (obj, name, getattr(obj, name, None))
        setattr(obj, name, value)

    def _route_controls_to_native(self, view) -> None:
        """Reuse the existing toolbar/search controls for the native view."""
        from PySide6.QtCore import Qt

        comparison = self.comparison

        def set_path_filter(text, *_args, **_kwargs):
            value = str(text).strip()
            directories_only = value.endswith("/")
            pattern = value.rstrip("/") if directories_only else value
            glob = any(char in pattern for char in "*?[")
            view.set_pattern(
                pattern,
                glob=glob,
                directories_only=directories_only,
                include_contents=directories_only,
            )

        def set_visible_actions(actions, *_args, **_kwargs):
            view.set_action_filter(actions or ())

        def search_matches(text, *_args, **_kwargs):
            return view.search(str(text).strip().casefold())

        def sort(column, order=Qt.SortOrder.AscendingOrder, *_args, **_kwargs):
            view.set_sort(column, order == Qt.SortOrder.DescendingOrder)

        def select_path(path, *_args, **_kwargs):
            view.select_path(path)
            comparison._hybrid_selected_path = path

        def row_path(row, *_args, **_kwargs):
            return view.path_of_row(row)

        self._patch_for_hybrid(comparison, 'set_path_filter', set_path_filter)
        self._patch_for_hybrid(comparison, 'set_visible_actions', set_visible_actions)
        self._patch_for_hybrid(comparison, 'set_action_filter', set_visible_actions)
        self._patch_for_hybrid(comparison, 'search_matches', search_matches)
        self._patch_for_hybrid(comparison.model, 'search_matches', search_matches)
        self._patch_for_hybrid(comparison.model, 'path_of_row_index', row_path)
        self._patch_for_hybrid(comparison.model, "_hybrid_row_count", view.row_count)
        # Legacy callers (and view-level tests) may send Space to the hidden
        # Python view. Its event filter asks _selected_paths(); answer from
        # the native selection so the existing decision path runs.
        self._patch_for_hybrid(
            comparison, "_selected_paths",
            lambda: [getattr(comparison, "_hybrid_selected_path", "")]
            if getattr(comparison, "_hybrid_selected_path", "") else [],
        )
        self._patch_for_hybrid(comparison, 'sort', sort)
        self._patch_for_hybrid(comparison, 'select_path', select_path)
        self._patch_for_hybrid(comparison, 'row_path', row_path)

        original_set_metadata = comparison.set_destination_metadata
        original_merge_metadata = comparison.merge_destination_metadata

        def set_destination_metadata(metadata, *, skip_view=False):
            # The Python view is hidden in hybrid mode; its rows are not built,
            # so a filter pass there would fail. Keep the data for the plan
            # but never ask the hidden view to rebuild.
            hidden = self._hybrid_view is not None
            original_set_metadata(metadata, skip_view=skip_view or hidden)
            if hidden:
                self._hybrid_view.set_destination_metadata(metadata, merge=False)

        def merge_destination_metadata(metadata, *, skip_view=False):
            hidden = self._hybrid_view is not None
            original_merge_metadata(metadata, skip_view=skip_view or hidden)
            if hidden:
                self._hybrid_view.set_destination_metadata(metadata, merge=True)

        self._patch_for_hybrid(comparison, 'set_destination_metadata', set_destination_metadata)
        self._patch_for_hybrid(comparison, 'merge_destination_metadata', merge_destination_metadata)

        def undo_decision(*_args, **_kwargs):
            result = original_undo()
            if result and self._hybrid_view is not None:
                self._sync_native_decisions()
            return result

        def redo_decision(*_args, **_kwargs):
            result = original_redo()
            if result and self._hybrid_view is not None:
                self._sync_native_decisions()
            return result

        original_undo = comparison.undo_decision
        original_redo = comparison.redo_decision
        self._hybrid_undo_original = original_undo
        self._hybrid_redo_original = original_redo
        self._patch_for_hybrid(comparison, 'undo_decision', undo_decision)
        self._patch_for_hybrid(comparison, 'redo_decision', redo_decision)
        self.undo_decision_action.triggered.disconnect()
        self.undo_decision_action.triggered.connect(undo_decision)
        self.redo_decision_action.triggered.disconnect()
        self.redo_decision_action.triggered.connect(redo_decision)

    def _sync_native_decisions(self) -> None:
        if self._hybrid_view is None:
            return
        from qpy_rsync.core.changes import ChangeDecision

        explicit = self.comparison.model.decisions.explicit_items()
        values = {
            path: 2 if decision is ChangeDecision.EXCLUDE else 1
            for path, decision in explicit
        }
        self._hybrid_view.apply_python_decisions(values)

    def _native_context_menu(self, pane: int, path: str, x: int, y: int) -> None:
        """Full row menu for the native comparison lists."""
        from pathlib import Path

        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication, QMenu

        from qpy_rsync.backend.rsync_patterns import phrases_for

        view = self._hybrid_view
        menu = QMenu(self)
        change = next(
            (
                item
                for item in self._last_changed_changes
                if str(item.path).rstrip("/") == path
            ),
            None,
        )
        is_dir = view.is_directory(path)
        heading = menu.addAction(path or "/")
        heading.setEnabled(False)
        menu.addSeparator()
        copy_path = menu.addAction("Copy Path")
        copy_name = menu.addAction("Copy Filename")
        copy_relative = menu.addAction("Copy Relative Path")
        open_file = None
        open_dir = None
        if path:
            menu.addSeparator()
            open_dir = menu.addAction(
                "Open Directory" if is_dir else "Open in Directory"
            )
            if not is_dir:
                open_file = menu.addAction("Open File")
        diff = None
        if change is not None:
            menu.addSeparator()
            diff = menu.addAction("Open in Diff Tool\t1")
        menu.addSeparator()
        excluded = view.decision_for_path(path) == 2
        include_item = menu.addAction(
            "Include Item" if excluded else "Exclude Item\tSpace"
        )
        reset_one = menu.addAction("Reset This Decision") if path else None
        reset_subtree = menu.addAction("Reset Subtree Decisions") if path else None
        reset_all = menu.addAction("Reset All Decisions")

        filter_actions = []
        if path:
            phrases = phrases_for(path, is_directory=is_dir)
            if phrases:
                filter_menu = menu.addMenu("Exclude via Filter")
                for phrase in phrases:
                    entry = filter_menu.addAction(phrase.label)
                    entry.setData(phrase.pattern)
                    filter_actions.append(entry)

        tool_actions = []
        enabled = [tool for tool in self._external_tools if tool.enabled]
        if path and enabled:
            tool_menu = menu.addMenu("Open with")
            side = "destination" if pane == 2 else "source"
            for number, tool in enumerate(enabled[:8], 2):
                entry = tool_menu.addAction(tool.name)
                entry.setToolTip(f"Shortcut: {number}")
                entry.setData((tool.name, path, side, is_dir))
                tool_actions.append(entry)

        fold_menu = menu.addMenu("Collapse / Expand")
        fold = None
        if path and is_dir:
            fold = fold_menu.addAction(
                "Expand Folder" if view.is_collapsed(path) else "Collapse Folder"
            )
            fold_menu.addSeparator()
        collapse_all = fold_menu.addAction("Collapse All Folders")
        expand_all = fold_menu.addAction("Expand All Folders")

        chosen = menu.exec(QPoint(x, y))
        if chosen is None:
            return
        if chosen is copy_path:
            QApplication.clipboard().setText(path)
        elif chosen is copy_name:
            QApplication.clipboard().setText(Path(path).name if path else "")
        elif chosen is copy_relative:
            QApplication.clipboard().setText(path.strip("/"))
        elif chosen is open_file or chosen is open_dir:
            root = self.source_edit.text() if pane == 0 else self.destination_edit.text()
            self._open_path(Path(root) / path, "file" if chosen is open_file else "directory")
        elif chosen is diff:
            self._open_diff_tool(change)
        elif chosen is include_item:
            view.set_decision_by_path(path, 0 if excluded else 2)
        elif chosen is reset_one:
            view.reset_decisions(path)
        elif chosen is reset_subtree:
            view.reset_decisions(path, subtree=True)
        elif chosen is reset_all:
            view.reset_decisions()
        elif chosen is fold:
            view.set_collapsed(path, not view.is_collapsed(path))
        elif chosen is collapse_all:
            view.collapse_all(True)
        elif chosen is expand_all:
            view.collapse_all(False)
        elif chosen in filter_actions:
            self._add_filter_phrase(chosen.data(), path)
        elif chosen in tool_actions:
            name, entry_path, side, directory = chosen.data()
            self._run_external_tool(name, entry_path, side, directory)

    def _native_header_menu(self, pane: int, x: int, y: int) -> None:
        """Checkable column editor for the native comparison headers."""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMenu

        from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

        view = self._hybrid_view
        side = "source" if pane == 0 else "destination"
        menu = QMenu(self)
        entries = {}
        for label, column in FlatComparisonView.OPTIONAL_COLUMNS[side]:
            entry = menu.addAction(label)
            entry.setCheckable(True)
            entry.setChecked(not view.is_column_hidden(pane, column))
            entries[entry] = (label, column)
        chosen = menu.exec(QPoint(x, y))
        if chosen is None:
            return
        _label, column = entries.get(chosen, ("", -1))
        if column < 0:
            return
        hidden = not chosen.isChecked()
        view.set_column_hidden(pane, column, hidden)
        # Size and Size (bytes) are alternatives: showing one hides the other.
        size_column = 2 if pane == 0 else 7
        bytes_column = 9 if pane == 0 else 10
        if not hidden and column == bytes_column:
            view.set_column_hidden(pane, size_column, True)
        elif not hidden and column == size_column:
            view.set_column_hidden(pane, bytes_column, True)

    def _on_native_selection(self, path_id: int) -> None:
        changes = self._last_changed_changes
        if 0 <= path_id < len(changes):
            self._hybrid_selected_path = str(changes[path_id].path).rstrip("/")

    def _on_native_decision(self, path_id: int, decision: int) -> None:
        """Mirror a native decision edit into Python's decision store."""
        from qpy_rsync.core.changes import ChangeDecision

        changes = self._last_changed_changes
        if 0 <= path_id < len(changes):
            targets = [str(changes[path_id].path).rstrip("/")]
        elif self._hybrid_view is not None:
            # Folder rows are synthesized after the change list: mirror the
            # subtree decision onto every change below that folder.
            folder = self._hybrid_view.path_of_id(path_id).rstrip("/")
            if not folder or folder.startswith("\x01"):
                return
            prefix = folder + "/"
            targets = [
                str(change.path).rstrip("/")
                for change in changes
                if str(change.path).rstrip("/").startswith(prefix)
            ]
        else:
            return
        model = self.comparison.model
        decisions = model.decisions
        before = model._snapshot()
        for path in targets:
            if decision == 2:  # Exclude
                decisions.set(path, ChangeDecision.EXCLUDE)
            else:
                decisions.reset(path)
        after = model._snapshot()
        if before != after:
            model.decision_history.record(before, after)
            model.history_changed.emit()
        model._refresh_effective_actions(set(targets))
        if self._hybrid_view is not None:
            self._hybrid_view.refresh_after_decision(path_id, decision)
        self._on_decision_changed(set(targets))
        # _on_decision_changed already marks the plan stale through
        # _overview_updated; avoid a second full stale pass here.
        self._invalidate_validated_plan(mark=False)

    def _set_cached_destination(self, paths: object | None) -> None:
        setter = getattr(self._inventory_service, "set_cached_destination", None)
        if setter is not None:
            setter(paths)

    def _source_preload_finished(self, token: int, extra: object) -> None:
        if self._closing or token != self._source_preload_token:
            return
        self._source_preload_token = 0
        result = _inventory_result(extra)
        self._cached_source_paths = result.source_paths
        self._inventory_service.set_cached_source(result.source_paths)
        count = len(result.source_paths or {})
        self._append_log(f"Source listing cached: {count:,} object(s).")

    def _fetch_destination_metadata(self) -> bool:
        """Start the destination listing; return whether it is still running."""
        if self._active_profile is None:
            return False
        if getattr(self.comparison.model, "exclusion", None) is None:
            return False
        # The inventory already knows the destination metadata.
        if self.inventory_after_compare_button.isChecked():
            return False
        changes = list(self._changed_changes())
        if not changes:
            return False
        listing_profile = (
            self._active_profile
            if self._metadata_two_pass
            else unfiltered_profile(self._active_profile)
        )
        self._log_spec(
            build_inventory_spec(listing_profile, listing_profile.destination)
        )
        self._metadata_token = self._metadata_service.gather(
            deepcopy(self._active_profile), changes
        )
        if self._inventory_preload:
            self._log_spec(
                build_inventory_spec(
                    self._active_profile, self._active_profile.source
                )
            )
            self._source_preload_token = self._source_preload_service.gather(
                deepcopy(self._active_profile), changes
            )
        return True

    def _changed_changes(self) -> list[object]:
        return [
            change
            for change in self._last_changed_changes
            if getattr(change, "action", None)
            is not ChangeAction.NO_CHANGE
        ]

    def _metadata_timeout(self) -> None:
        if self._closing or not self._metadata_pending:
            return
        self._metadata_service.cancel()
        self._metadata_token = 0
        self._metadata_pending = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Destination metadata timed out")
        self._set_status(
            "Comparison complete; destination metadata timed out.", "warning"
        )
        self._append_log(
            "Destination metadata listing timed out after 60 s.", severity="warning"
        )
        self._finish_comparison_status()

    def _metadata_failed(self, token: int, message: str) -> None:
        if self._closing or token != self._metadata_token:
            return
        self._metadata_watchdog.stop()
        self._metadata_token = 0
        was_pending = self._metadata_pending
        self._metadata_pending = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Destination metadata unavailable")
        self._append_log(f"Destination metadata failed: {message}", severity="warning")
        if was_pending:
            self._set_status(
                "Comparison complete; destination metadata could not be read.",
                "warning",
            )
            self._finish_comparison_status()

    def _announce_comparison_complete(self) -> None:
        if self._comparison_announced:
            return
        self._comparison_announced = True
        self._play_completion_sound("success")
        self._append_log(
            f"STATE comparison-complete changes={self._last_compare_count}"
        )
        self._end_bulk_logging()

    def _finish_comparison_status(self) -> None:
        self._announce_comparison_complete()
        count = self._last_compare_count
        if self._last_phase_started is not None:
            self._append_log(
                "Comparison ready in "
                f"{time.monotonic() - self._last_phase_started:.2f} s."
            )
            self._last_phase_started = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText("Comparison completed")
        self._set_state(
            f"Comparison complete: {count} changed item(s).", "success"
        )

    def _metadata_finished(self, token: int, extra: object) -> None:
        if self._closing or token != self._metadata_token:
            return
        self._metadata_watchdog.stop()
        self._metadata_token = 0
        was_pending = self._metadata_pending
        self._metadata_pending = False
        result = _inventory_result(extra)
        # Keep the full destination listing so a later Show-unchanged only
        # needs to enumerate the source tree.
        self._set_cached_destination(result.destination_paths)
        if not result.destination_metadata:
            if was_pending:
                self._finish_comparison_status()
            return
        with timed("metadata.merge", entries=len(result.destination_metadata)):
            self.comparison.merge_destination_metadata(
                result.destination_metadata,
                skip_view=self._hybrid_view is not None,
            )
        # The plan was first built before this asynchronous listing arrived.
        # Only the deleted-size summary depends on it, so avoid a full rebuild.
        with timed("metadata.plan"):
            if not self._update_plan_deleted_size():
                self._refresh_plan_summary()
        self._append_log(
            f"Destination metadata: {len(result.destination_metadata)} object(s)."
        )
        if was_pending:
            self._finish_comparison_status()

    def _start_inventory(self, key: object, changed: list[object]) -> None:
        """List both trees in the background."""
        if self._active_profile is not None:
            missing = self._missing_local_directories(self._active_profile)
            if missing:
                self._warn_missing_local_directories(missing, "Inventory")
                return
        self._inventory_pending_key = key
        if self._active_profile is not None:
            if self._cached_source_paths is not None:
                self._append_log(
                    "$ rsync --list-only <source> (reused from preload)"
                )
            else:
                self._log_spec(
                    build_inventory_spec(
                        self._active_profile, self._active_profile.source
                    )
                )
            if self._has_cached_destination():
                self._append_log(
                    "$ rsync --list-only <destination> (reused from metadata listing)"
                )
            else:
                self._log_spec(
                    build_inventory_spec(
                        self._active_profile, self._active_profile.destination
                    )
                )
        if self.show_unchanged.isChecked():
            self.progress_label.setText(
                "Listing both trees for the unchanged items..."
            )
        else:
            self.progress_label.setText("Gathering unchanged items...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._append_log("STATE inventory-started")
        self._append_log(
            "Listing both trees to find the unchanged items, because the "
            "unchanged toggle asks for them."
            if self.show_unchanged.isChecked()
            else "Listing both trees to find the unchanged items.",
            severity="info",
        )
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
        self._set_cached_destination(result.destination_paths)
        self._inventory_cache_key = key
        self._inventory_cache = list(result.unchanged)
        # The listing knows the destination of every object, so the tree can
        # show its size and date.
        self.comparison.set_destination_metadata(
            result.destination_metadata,
            skip_view=self._hybrid_view is not None,
        )
        if not self.show_unchanged.isChecked():
            # When unchanged items will be added, their set_changes rebuilds
            # the plan anyway; doing it twice costs seconds on a large tree.
            self._refresh_plan_summary()
        if self.show_unchanged.isChecked():
            self._populate_unchanged(
                changed + list(result.unchanged), len(result.unchanged)
            )
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
        count = len(result.unchanged)
        self.progress_label.setText(
            self._inventory_summary(count)
            if self.show_unchanged.isChecked()
            else f"Inventory complete: {count:,} unchanged item(s) available.",
        )
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
            self._set_comparison_changes(list(self._last_changed_changes))

    def _comparison_error(self, message: str) -> None:
        if self._closing:
            return
        if self._active_compare_generation != self._compare_generation:
            return
        self._log_rsync_elapsed("dry run")
        self.compare_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_label.setText("Comparison failed")
        self._set_state("Comparison failed.", "error")
        self._append_log(message, severity="error")
        self._end_bulk_logging()
        QMessageBox.critical(self, "Comparison failed", message)

    def _start_rsync_clock(self, label: str) -> None:
        self._rsync_started_at[label] = (time.monotonic(), datetime.now())
        self._append_log(f"rsync {label} start clock set.")

    def _log_rsync_elapsed(self, label: str) -> None:
        started = self._rsync_started_at.pop(label, None)
        if started is None:
            return
        monotonic_start, wall_start = started
        elapsed = time.monotonic() - monotonic_start
        wall = (datetime.now() - wall_start).total_seconds()
        self._append_log(
            f"rsync {label} finished in {elapsed:.2f} s "
            f"(wall {wall:.2f} s)."
        )

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
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-4]
        for line in normalized.replace("\r", "\n").splitlines() or [""]:
            self._log_buffer.append((line, rsync, severity.lower(), timestamp))
        if self._bulk_logging:
            if not self._log_flush_timer.isActive():
                self._log_flush_timer.start()
            return
        self._flush_log()

    def _flush_rsync_pending(self) -> None:
        if not self._rsync_pending:
            return
        lines = self._rsync_pending
        self._rsync_pending = []
        self._write_session_log("\n".join(lines), rsync=True)

    def _append_rsync_log(self, text: str) -> None:
        # Raw rsync output is opt-in: on a large tree it can reach hundreds of
        # MB per run and costs measurable time in this single-threaded path.
        if not self._rsync_output_logging:
            return
        if self._bulk_logging or self._bulk_rsync:
            # Never let an itemized record reach the journal widget during a
            # bulk comparison, including late lines after the final flush.
            # Batch the raw file writes: one timestamp and one flush per
            # thousand lines instead of one per record.
            lines = text.rstrip("\r\n").splitlines()
            if lines:
                self._rsync_pending.extend(lines)
                self._bulk_record_count += len(lines)
                if len(self._rsync_pending) >= 1000:
                    self._flush_rsync_pending()
            return
        self._append_log(text, rsync=True)

    def _flush_log(self) -> None:
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        if not self._log_buffer:
            return
        entries = self._log_buffer
        self._log_buffer = []
        # Every line goes to the session log. During a large comparison the
        # itemized rsync records go only there: inserting hundreds of
        # thousands of blocks into the journal widget costs minutes even when
        # batched, and the session log is the complete record.
        app_lines = [line for line, rsync, _s, _t in entries if not rsync]
        rsync_lines = [line for line, rsync, _s, _t in entries if rsync]
        if app_lines:
            self._write_session_log("\n".join(app_lines))
        if rsync_lines:
            self._write_session_log("\n".join(rsync_lines), rsync=True)
        journal_entries = [
            entry for entry in entries if not (self._bulk_rsync and entry[1])
        ]
        if self._bulk_rsync:
            self._bulk_record_count += sum(1 for entry in entries if entry[1])
        if not journal_entries:
            return
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        time_format = QTextCharFormat()
        time_format.setForeground(QColor("#6b7280"))
        formats: dict[tuple[bool, str], QTextCharFormat] = {}
        for index, (line, rsync, severity, timestamp) in enumerate(journal_entries):
            key = (rsync, severity)
            content_format = formats.get(key)
            if content_format is None:
                content_format = self._journal_format(rsync, severity)
                formats[key] = content_format
            if index:
                cursor.insertBlock()
            cursor.insertText(f"{timestamp} ", time_format)
            cursor.insertText(line, content_format)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _journal_format(self, rsync: bool, severity: str) -> QTextCharFormat:
        content_format = QTextCharFormat()
        palette = self.log.palette()
        dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
        if rsync:
            color = QColor("#cbd5e1" if dark else "#6b7280")
        elif severity == "logsize":
            color = QColor("#fb923c" if dark else "#EA580C")
        elif severity == "warning":
            color = QColor("#22d3ee" if dark else "#0891B2")
        elif severity == "error":
            color = QColor("#f87171" if dark else "#B91C1C")
        elif severity == "success":
            color = QColor("#4ade80" if dark else "#15803D")
        else:
            # Use the theme's own text colour so dark themes stay readable.
            color = palette.color(QPalette.ColorRole.Text)
        content_format.setForeground(color)
        return content_format

    def _append_transient_log(self, text: str) -> None:
        """Keep rsync progress in the session log, not in the journal."""
        if not self._rsync_output_logging:
            return
        normalized = text.rstrip("\r\n")
        if normalized:
            self._write_session_log(normalized, rsync=True)

    def _begin_bulk_logging(self) -> None:
        self._bulk_logging = True
        self._bulk_rsync = True
        self._bulk_record_count = 0

    def _end_bulk_logging(self) -> None:
        self._flush_rsync_pending()
        self._bulk_logging = False
        if self._log_flush_timer.isActive():
            self._log_flush_timer.stop()
        self._flush_log()
        count = self._bulk_record_count
        self._bulk_rsync = False
        self._bulk_record_count = 0
        if count:
            self._append_log(
                f"{count:,} rsync record(s) written to the session log."
            )

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
        current = decode_text(settings.value("profile/current_path", "")) or ""
        if current:
            path = Path(current).expanduser()
            if path.is_file():
                try:
                    self._apply_profile(load_profile(path))
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                else:
                    self._profile_path = path
                    return True
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

    # ------------------------------------------------------------------ #
    # Compare layout
    # ------------------------------------------------------------------ #
    def _main_splitter_moved(self, _position: int, _index: int) -> None:
        if self._layout_mode == "wide" and self.main_splitter.count() == 2:
            self._wide_overview_width = self.main_splitter.sizes()[1]

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self._layout_mode == "wide" and self._wide_overview_width:
            total = sum(self.main_splitter.sizes())
            width = min(self._wide_overview_width, max(200, total - 200))
            self.main_splitter.setSizes([total - width, width])

    @staticmethod
    def _layout_state_key(mode: str) -> str:
        return f"main-window/layout-state-{mode}"

    def _save_current_layout_state(self) -> None:
        settings = app_settings()
        settings.setValue(
            self._layout_state_key(self._layout_mode),
            encode_binary(self.main_splitter.saveState()),
        )
        settings.sync()

    def _refresh_layout_button(self) -> None:
        label = next(
            (text for mode, text in LAYOUT_MODES if mode == self._layout_mode),
            "Normal",
        )
        self.layout_button.setToolTip(
            f"Compare layout: {label} — click to change\n"
            "Ctrl+Tab / Ctrl+Shift+Tab cycles the modes"
        )
        for mode, action in self.layout_actions.items():
            action.setChecked(mode == self._layout_mode)  # type: ignore[union-attr]
        for mode, action in getattr(self, "view_layout_actions", {}).items():
            action.setChecked(mode == self._layout_mode)  # type: ignore[union-attr]

    def _cycle_layout(self, delta: int) -> None:
        names = [mode for mode, _ in LAYOUT_MODES]
        try:
            index = names.index(self._layout_mode)
        except ValueError:
            index = 0
        self._set_layout_mode(names[(index + delta) % len(names)])

    def _cycle_layout_forward(self) -> None:
        self._cycle_layout(1)

    def _cycle_layout_backward(self) -> None:
        self._cycle_layout(-1)

    def _set_layout_mode(self, mode: str, *, restore: bool = True) -> None:
        """Switch between Normal, Compare-only and Compare+overview layouts."""
        if mode not in {name for name, _ in LAYOUT_MODES}:
            mode = "normal"
        if mode == self._layout_mode and restore:
            return
        if self._layout_mode == "normal":
            self._wide_overview_width = self.overview.width()
        self._save_current_layout_state()
        parent = self.centralWidget()
        # Park both widgets outside the splitters while the hierarchy changes.
        self.log_panel.setParent(parent)
        self.overview.setParent(parent)
        self.log_panel.hide()
        self.overview.hide()

        if mode == "focus":
            self.main_splitter.setOrientation(Qt.Orientation.Vertical)
            self.log_panel.setParent(parent)
            self.log_panel.hide()
        elif mode == "wide":
            self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.main_splitter.addWidget(self.overview)
            # Side-by-side, the overview keeps its current width but can be
            # dragged narrower; the wide minimum is much smaller.
            self.overview.setMinimumWidth(180)
            self.overview.show()
        else:
            if self._overview_min_width is not None:
                self.overview.setMinimumWidth(self._overview_min_width)
            self.log_splitter.addWidget(self.overview)
            self.overview.show()
            self.main_splitter.setOrientation(Qt.Orientation.Vertical)
            self.main_splitter.addWidget(self.log_panel)
            self.log_panel.show()

        self._layout_mode = mode
        state = (
            decode_binary(
                app_settings().value(self._layout_state_key(mode), "")
            )
            if restore
            else None
        )
        if state is not None:
            self.main_splitter.restoreState(state)
        elif mode == "normal":
            self.main_splitter.setSizes([380, 250])
        elif mode == "wide":
            available = max(400, self.main_splitter.width())
            width = self._wide_overview_width or int(available * 0.4)
            width = min(width, max(200, available - 200))
            self.main_splitter.setSizes([available - width, width])
        self._refresh_layout_button()
        settings = app_settings()
        settings.setValue("main-window/layout-mode", mode)
        settings.sync()

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
        mode = str(settings.value("main-window/layout-mode", "normal"))
        # The normal hierarchy is already in place; switching is only needed
        # for a remembered Focus or Wide mode.
        if mode != "normal":
            self._set_layout_mode(mode)
        else:
            state = decode_binary(
                settings.value(self._layout_state_key("normal"), "")
            )
            if state is not None:
                self.main_splitter.restoreState(state)
        self._refresh_layout_button()
        # The auto-inventory choice belongs to the profile now. Drop the old
        # global value so it cannot be mistaken for the active state.
        settings.remove("comparison/inventory-after-compare")
        settings.sync()

    def _inventory_after_compare_changed(self, checked: bool) -> None:
        """The auto-inventory choice is now part of the current profile."""
        with timed("ui.inventory_toggle", checked=checked):
            self._inventory_toggle_body(checked)

    def _inventory_toggle_body(self, checked: bool) -> None:
        self._refresh_profile_marker()
        if not checked:
            # Disabling is only a profile setting. Stop a listing already in
            # flight, but do not rebuild the view or change other toggles.
            self._inventory_service.cancel()
            self._inventory_token = 0
            self._inventory_pending_key = None
            return
        if (
            checked
            and self._active_profile is not None
            and self.comparison.model.changes
            and not self.comparison.model.stale
        ):
            # Turning the toggle on for an existing comparison starts the
            # inventory that would otherwise have run after the comparison.
            metadata_started = self._fetch_destination_metadata()
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
        if self._hybrid_view is not None:
            self._hybrid_view.shutdown()
        settings = app_settings()
        settings.setValue(
            "main-window/geometry", encode_binary(self.saveGeometry())
        )
        settings.setValue("main-window/state", encode_binary(self.saveState()))
        self._save_current_layout_state()
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

            self._save_profile_on_exit_if_modified(_current, _baseline)
        except Exception:  # noqa: BLE001
            pass
        self._flush_log()
        self._close_session_log()
        super().closeEvent(event)  # type: ignore[arg-type]
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()  # type: ignore[union-attr]

    def _save_profile_on_exit_if_modified(self, current, baseline) -> None:
        try:
            if (
                os.environ.get("QT_QPA_PLATFORM") != "offscreen"
                and baseline is not None
                and not self._same_profile(current, baseline)
            ):
                # Tell the user *what* changed instead of a generic prompt.
                current_dict = current.to_dict()
                baseline_dict = baseline.to_dict()
                changed_fields = [
                    key
                    for key in current_dict
                    if key not in {"profile_id", "name"}
                    and current_dict[key] != baseline_dict.get(key)
                ]
                reason = (
                    "Changed: " + ", ".join(sorted(changed_fields))
                    if changed_fields
                    else "Profile settings changed."
                )
                target = self._profile_path
                if target is None:
                    question = (
                        f"{reason}\n\nNo profile file is associated with these "
                        "settings yet. Save them as a new profile?"
                    )
                else:
                    question = (
                        f"{reason}\n\nSave the changes to {target.name}?"
                    )
                answer = QMessageBox.question(
                    self,
                    "Save profile",
                    question,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    if target is None:
                        path, _selected = QFileDialog.getSaveFileName(
                            self,
                            "Save Profile",
                            str(profiles_directory() / "qpy-rsync-profile.json"),
                            "JSON (*.json)",
                        )
                        if path:
                            target = Path(path)
                    if target is not None:
                        save_profile(target, self._profile())
                        self._remember_profile_path(target)
                        self._baseline_profile = self._profile()
                        self._save_recent_profile()
                        self._append_log(f"Profile saved: {target}")
        except Exception:  # noqa: BLE001
            pass
