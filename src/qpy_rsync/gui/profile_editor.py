"""The profile editor: transfer, preservation, backup, policy and filters."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.core.enums import ConflictPolicy, DeleteTiming, SyncMode
from qpy_rsync.core.models import FilterRule, PreservationOptions, SyncProfile, TransferOptions

from .filter_editor import FilterEditorWidget

SECTIONS = ("options", "preservation", "backup", "filters")


def _combo(values, current):
    combo = QComboBox()
    for value in values:
        combo.addItem(value.value.replace("_", " ").capitalize(), value)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


class ProfileEditorDialog(QDialog):
    """Edit the settings a profile owns that the main toolbar cannot show."""

    def __init__(self, profile: SyncProfile, parent=None, section: str = "transfer") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit profile")
        self.resize(640, 560)
        self._profile = deepcopy(profile)

        transfer = self._profile.transfer
        preservation = self._profile.preservation

        self.sync_mode = _combo(SyncMode, transfer.sync_mode)
        self.delete_timing = _combo(DeleteTiming, transfer.delete_timing)
        self.compress = QCheckBox("Compress data during transfer")
        self.fuzzy = QCheckBox("Use fuzzy transfers")
        self.whole_file = QCheckBox("Use whole-file transfers")
        self.copy_links = QCheckBox("Copy symlinks as copies")
        self.one_file_system = QCheckBox("Do not cross file-system boundaries")
        self.ignore_times = QCheckBox("Ignore modification times")
        self.sparse = QCheckBox("Transfer sparse files efficiently")
        self.inventory_after_compare = QCheckBox(
            "Fetch the unchanged inventory automatically after a comparison"
        )
        self.inventory_after_compare.setChecked(profile.inventory_after_compare)
        for checkbox, value in (
            (self.compress, transfer.compress),
            (self.fuzzy, transfer.fuzzy),
            (self.whole_file, transfer.whole_file),
            (self.copy_links, transfer.copy_links),
            (self.one_file_system, transfer.one_file_system),
            (self.ignore_times, transfer.ignore_times),
            (self.sparse, transfer.sparse),
        ):
            checkbox.setChecked(value)
        options_tab = QWidget(self)
        options_layout = QVBoxLayout(options_tab)
        from PySide6.QtWidgets import QGroupBox

        transfer_group = QGroupBox("Transfer", options_tab)
        transfer_layout = QFormLayout(transfer_group)
        transfer_layout.addRow("Sync mode", self.sync_mode)
        transfer_layout.addRow("Delete timing", self.delete_timing)
        options_layout.addWidget(transfer_group)

        behaviours_group = QGroupBox("Transfer options", options_tab)
        behaviours_layout = QVBoxLayout(behaviours_group)
        for checkbox in (
            self.compress,
            self.fuzzy,
            self.whole_file,
            self.copy_links,
            self.one_file_system,
            self.ignore_times,
            self.sparse,
        ):
            behaviours_layout.addWidget(checkbox)
        options_layout.addWidget(behaviours_group)

        self.archive = QCheckBox("Archive mode")
        self.hard_links = QCheckBox("Preserve hard links")
        self.acls = QCheckBox("Preserve ACLs")
        self.xattrs = QCheckBox("Preserve extended attributes")
        self.numeric_ids = QCheckBox("Keep numeric IDs")
        for checkbox, value in (
            (self.archive, preservation.archive),
            (self.hard_links, preservation.hard_links),
            (self.acls, preservation.acls),
            (self.xattrs, preservation.xattrs),
            (self.numeric_ids, preservation.numeric_ids),
        ):
            checkbox.setChecked(value)
        preservation_tab = QWidget(self)
        preservation_layout = QVBoxLayout(preservation_tab)
        for checkbox in (
            self.archive,
            self.hard_links,
            self.acls,
            self.xattrs,
            self.numeric_ids,
        ):
            preservation_layout.addWidget(checkbox)
        preservation_layout.addStretch(1)

        self.backup_dir = QLineEdit(self._profile.backup.directory)
        self.protect_backup = QCheckBox("Protect nested backup directory")
        self.protect_backup.setChecked(self._profile.backup.protect_nested)
        backup_tab = QWidget(self)
        backup_layout = QFormLayout(backup_tab)
        backup_layout.addRow("Backup directory", self.backup_dir)
        backup_layout.addRow("", self.protect_backup)
        backup_hint = QLabel(
            "An empty directory disables backups. The same directory is used "
            "by the backup toolbar button and by the profile."
        )
        backup_hint.setWordWrap(True)
        backup_layout.addRow("", backup_hint)

        self.conflict_policy = _combo(ConflictPolicy, self._profile.conflict_policy)
        policy_group = QGroupBox("Conflict policy", options_tab)
        policy_layout = QFormLayout(policy_group)
        policy_layout.addRow("Policy", self.conflict_policy)
        policy_hint = QLabel(
            "The conflict policy controls what happens when a file changes on "
            "both sides between the comparison and the synchronization."
        )
        policy_hint.setWordWrap(True)
        policy_layout.addRow("", policy_hint)
        options_layout.addWidget(policy_group)
        comparison_group = QGroupBox("Comparison", options_tab)
        comparison_layout = QVBoxLayout(comparison_group)
        comparison_layout.addWidget(self.inventory_after_compare)
        options_layout.addWidget(comparison_group)
        options_layout.addStretch(1)

        self.filter_widget = FilterEditorWidget(
            self._profile.filters, self, text=self._profile.filter_text or None
        )

        from PySide6.QtWidgets import QTabWidget

        self.tabs = QTabWidget(self)
        self.tabs.addTab(options_tab, "Options")
        self.tabs.addTab(preservation_tab, "Preservation")
        self.tabs.addTab(backup_tab, "Backup")
        self.tabs.addTab(self.filter_widget, "Filters")
        self.show_section(section)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

    def show_section(self, section: str) -> None:
        try:
            index = SECTIONS.index(section)
        except ValueError:
            index = 0
        self.tabs.setCurrentIndex(index)

    def profile(self) -> SyncProfile:
        profile = deepcopy(self._profile)
        profile.transfer = TransferOptions(
            sync_mode=self.sync_mode.currentData(),
            delete_timing=self.delete_timing.currentData(),
            compress=self.compress.isChecked(),
            fuzzy=self.fuzzy.isChecked(),
            whole_file=self.whole_file.isChecked(),
            copy_links=self.copy_links.isChecked(),
            one_file_system=self.one_file_system.isChecked(),
            ignore_times=self.ignore_times.isChecked(),
            sparse=self.sparse.isChecked(),
        )
        profile.preservation = PreservationOptions(
            archive=self.archive.isChecked(),
            hard_links=self.hard_links.isChecked(),
            acls=self.acls.isChecked(),
            xattrs=self.xattrs.isChecked(),
            numeric_ids=self.numeric_ids.isChecked(),
        )
        from qpy_rsync.core.models import BackupOptions

        profile.backup = BackupOptions(
            directory=self.backup_dir.text().strip(),
            protect_nested=self.protect_backup.isChecked(),
        )
        profile.conflict_policy = self.conflict_policy.currentData()
        profile.inventory_after_compare = self.inventory_after_compare.isChecked()
        profile.filter_text = self.filter_widget.text()
        profile.filters = self.filter_widget.rules()
        return profile

    def rules(self) -> list[FilterRule]:
        return self.filter_widget.rules()

    def _accept_if_valid(self) -> None:
        error = self.filter_widget.first_error()
        if error is not None:
            self.show_section("filters")
            self.filter_widget.reveal_error()
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Invalid filters",
                f"Line {error[0]}: {error[1]}\n\nCorrect the highlighted line first.",
            )
            return
        self.accept()
