"""A short explanation of the workflow, shown from Help -> How-To."""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

HOW_TO_TEXT = """\
qpy-rsync compares two locations and only writes after you reviewed the
result.

1. Source and Destination
   Enter a local path (/home/alice/data or ~/data) or one remote path in the
   form [user@]host:/absolute/path. At most one side may be remote.

2. Method (F4)
   Update copies new and changed items and keeps items that exist only in
   the destination. Mirror makes the destination match the source, including
   deletions. New Only copies missing items and never updates or deletes.

3. Compare (F5)
   Runs rsync in dry-run mode. Nothing is written. The three panes show the
   source, the action and the destination of every item, and the overview
   summarizes the folders.

4. Actions
   Each row carries an action in the middle pane:
     +  new item             =  unchanged item (faded checkmark)
     up updated content      =  folder on both sides
     pin metadata only       x  deleted item
     replace                 arrow left  kept in destination
   Checkboxes include or exclude an item. Items that cannot be chosen, such
   as unchanged items, carry no checkbox. The Actions menu resets decisions.

   Space stashes the selected item: it is temporarily left out of the sync and
   kept aside for this comparison only. The crossed eye on the right of the
   Actions column stashes and restores it, the filter bar has a "Show stashed
   items" toggle, and its right-click menu offers "Restore All Stashed".
   The arrow in front of a folder collapses or expands its contents in the
   list only: the sync, the totals and the overview keep every item. Left and
   Right do the same from the keyboard, and "Collapse All Folders" /
   "Expand All Folders" are in the Actions menu.

5. Verify Actions (F8)
   Builds the execution plan from your selection and checks it with a second
   rsync dry run. It runs only when checkbox decisions were changed after the
   comparison; otherwise the fresh comparison is reused. Verification is the
   step that proves the plan before anything is written, and synchronization
   stays disabled until it succeeds. Use Pause (F11) to suspend a running
   dry run or transfer and Resume to continue it.

6. Synchronize (F9)
   Opens the confirmation dialog with the counts, the total size, the backup
   settings and the destructive warning. Synchronize Now writes the verified
   plan. rsync runs with the same filters that were verified, and the
   comparison is refreshed afterwards.

7. Journal
   The journal keeps the commands, the itemized records and the application
   states. rsync progress belongs to the session log file only, so the
   journal stays readable. The State field next to the journal shows the
   current state.

8. Inventory (F6)
   The Show unchanged button (or the Inventory toggle next to Compare) lists
   both trees and adds the unchanged items. The listing is cached per
   comparison, so the button never runs it twice.

9. Profiles (F2/F3)
   Save and load the whole setup in $XDG_CONFIG_HOME/qpy-rsync/profiles.

10. Large comparisons
    Settings (Ctrl+,) limits how many direct items a folder may have to open
    automatically (default 256). Larger folders stay collapsed and carry an
    amber marker; their tooltip explains the limit. Branches without a large
    folder still open normally. Expand a folder by hand or raise the limit.
    Inventory reports the number of listed objects while it works, and adding
    a large unchanged set shows a population message.
"""


class HowToDialog(QDialog):
    """A scrollable explanation of the application."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How-To")
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        viewer = QPlainTextEdit()
        viewer.setObjectName("howto-text")
        viewer.setReadOnly(True)
        viewer.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        viewer.setPlainText(HOW_TO_TEXT)
        viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(viewer, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def show_how_to(parent: QWidget | None = None) -> None:
    HowToDialog(parent).exec()
