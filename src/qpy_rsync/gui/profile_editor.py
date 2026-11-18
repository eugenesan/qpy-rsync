"""The profile editor: transfer, preservation, backup, policy and filters."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.core.enums import ConflictPolicy, DeleteTiming, SyncMode
from qpy_rsync.core.models import FilterRule, PreservationOptions, SyncProfile, TransferOptions

from .filter_editor import FilterEditorWidget
from .icons import folder_open_icon, open_icon

SECTIONS = ("options", "preservation", "backup", "filters")


def _combo(values, current):
    combo = QComboBox()
    for value in values:
        combo.addItem(value.value.replace("_", " ").capitalize(), value)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


def _rsync_tip(widget, option: str, explanation: str) -> None:
    widget.setToolTip(f"{option}\n{explanation}")


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
        self.checksum = QCheckBox("Compare files by checksum")
        self.partial_dir = QCheckBox("Keep partial files in .rsync-partial")
        self.inplace = QCheckBox("Update files in place")
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
            (self.checksum, transfer.checksum),
            (self.partial_dir, bool(transfer.partial_dir)),
            (self.inplace, transfer.inplace),
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
            self.checksum,
            self.partial_dir,
            self.inplace,
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
        self.backup_browse = QToolButton(self)
        self.backup_browse.setIcon(open_icon())
        self.backup_browse.setToolTip("Browse for the backup directory")
        self.backup_browse.setAccessibleName("Browse backup directory")
        self.backup_browse.clicked.connect(self._browse_backup_dir)
        self.backup_open = QToolButton(self)
        self.backup_open.setIcon(folder_open_icon())
        self.backup_open.setToolTip("Open the backup directory")
        self.backup_open.setAccessibleName("Open backup directory")
        self.backup_open.clicked.connect(self._open_backup_dir)
        self.backup_dir.textChanged.connect(self._update_backup_buttons)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self.backup_dir, 1)
        backup_row.addWidget(self.backup_browse)
        backup_row.addWidget(self.backup_open)
        self.protect_backup = QCheckBox("Protect nested backup directory")
        self.protect_backup.setChecked(self._profile.backup.protect_nested)
        backup_tab = QWidget(self)
        backup_layout = QFormLayout(backup_tab)
        backup_layout.addRow("Backup directory", backup_row)
        backup_layout.addRow("", self.protect_backup)
        backup_hint = QLabel(
            "An empty directory disables backups. The same directory is used "
            "by the backup toolbar button and by the profile."
        )
        backup_hint.setWordWrap(True)
        backup_layout.addRow("", backup_hint)
        self._update_backup_buttons()

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
            self._profile.filters, self, text=self._profile.filter_text
        )

        self._apply_tooltips()

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

    def _backup_path(self) -> Path | None:
        text = self.backup_dir.text().strip()
        if not text:
            return None
        from pathlib import Path

        return Path(text).expanduser()

    def _update_backup_buttons(self) -> None:
        path = self._backup_path()
        self.backup_open.setEnabled(path is not None and path.is_dir())

    def _browse_backup_dir(self) -> None:
        path = self._backup_path()
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose backup directory",
            str(path) if path is not None and path.is_dir() else "",
        )
        if chosen:
            self.backup_dir.setText(chosen)

    def _open_backup_dir(self) -> None:
        path = self._backup_path()
        if path is not None and path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _apply_tooltips(self) -> None:
        """Show the rsync option behind every setting that adds one."""
        _rsync_tip(
            self.sync_mode,
            "--delete-* / --ignore-existing",
            "Update transfers changes, Mirror also deletes destination-only "
            "items, New Only copies missing items and never updates.",
        )
        _rsync_tip(
            self.delete_timing,
            "--delete-before / --delete-during / --delete-delay / --delete-after",
            "When rsync removes destination-only items during a Mirror sync.",
        )
        for widget, option, explanation in (
            (self.compress, "--compress / --no-compress", "Compress transfer data."),
            (self.checksum, "--checksum", "Compare whole-file checksums instead of size and time."),
            (
                self.partial_dir,
                "--partial-dir=.rsync-partial and --partial",
                "Keep interrupted transfers in a side folder so they can resume.",
            ),
            (self.inplace, "--inplace", "Write updated files directly instead of replacing them."),
            (self.fuzzy, "--fuzzy", "Use a similar local file as the transfer basis."),
            (self.whole_file, "--whole-file", "Copy whole files instead of using delta transfer."),
            (self.copy_links, "--copy-links", "Copy symlink targets as files or folders."),
            (self.one_file_system, "--one-file-system", "Do not cross mounted file-system boundaries."),
            (self.ignore_times, "--ignore-times", "Transfer files even when size and time match."),
            (self.sparse, "--sparse", "Store sequences of zeroes efficiently."),
            (self.archive, "--archive", "Recurse and preserve permissions, times, links and devices."),
            (self.hard_links, "--hard-links", "Preserve hard links between files."),
            (self.acls, "--acls", "Preserve POSIX access control lists."),
            (self.xattrs, "--xattrs", "Preserve extended attributes."),
            (self.numeric_ids, "--numeric-ids", "Keep numeric owner and group IDs."),
            (self.backup_dir, "--backup and --backup-dir=DIRECTORY", "Keep replaced files in a destination-side backup folder."),
            (self.protect_backup, "P /.backup/***", "Protect the nested backup folder from deletion."),
        ):
            _rsync_tip(widget, option, explanation)

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
            checksum=self.checksum.isChecked(),
            partial_dir=".rsync-partial" if self.partial_dir.isChecked() else "",
            inplace=self.inplace.isChecked(),
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
