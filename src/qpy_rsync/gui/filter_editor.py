from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from qpy_rsync.backend.rsync_filters import validate_rule
from qpy_rsync.backend.rsync_filters import export_filter_file, import_filter_file
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


_RSFILTER_HELP = '''rsync filter rules

Each non-empty, non-comment line is one rule, applied in order; rsync
stops at the first matching rule.

Operator prefixes (rsync filter syntax):
  + pattern   include the matching path
  - pattern   exclude the matching path
  P pattern   protect (do not delete) the matching path
  R pattern   risk (allow deletion) of the matching path
  H pattern   hide the matching path
  S pattern   show the matching path
  : pattern   send a rule to the daemon side
  . pattern   merge a per-directory filter file
  !           clear the current list of rules
  (no prefix) treated as an exclusion: "- pattern"

Lines without an operator are interpreted as exclusions.

Comments:
  A line starting with "#" is a comment and is ignored. Commenting or
  uncommenting a rule is the only way to enable or disable it.

Patterns:
  *  matches any path component, but stops at slashes
  ** matches anything, including slashes
  ?  matches any single character
  [..] character class
  A trailing "/" matches directories only.
  A leading "/" anchors the pattern to the transfer root.

Examples:
  __pycache__/        exclude any __pycache__ directory
  *.pyc               exclude every .pyc file
  + important.txt     include important.txt even if excluded above
  - main.py           exclude main.py
  P cache/***         protect the cache tree from deletion
'''

_EXAMPLE_TEXT = """# Order of filters is important.
# Rsync stops at the first matching rule.
#
# Lines without an operator are treated as exclusions.
#
# Exclusions
#__pycache__/
#*.pyc
#- main.py
#
# Inclusions
#+ important.txt
#
# Advanced
#P cache/***
"""

_OPERATORS = ("+", "-", "P", "R", "H", "S", ":")


def _line_to_rule(line: str) -> FilterRule | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith(_OPERATORS):
        text = stripped
    else:
        text = f"- {stripped}"
    return FilterRule(text, rule_type=FilterRuleType.ADVANCED)


def _rules_to_text(rules: list[FilterRule]) -> str:
    lines: list[str] = []
    for item in rules:
        if item.rule_type is FilterRuleType.INCLUDE:
            base = item.rule if item.rule.lstrip().startswith("+") else f"+ {item.rule}"
        elif item.rule_type is FilterRuleType.EXCLUDE:
            base = item.rule if item.rule.lstrip().startswith("-") else item.rule
        else:
            base = item.rule
        if item.comment:
            lines.append(f"# {item.comment}")
        if not item.enabled:
            base = f"# {base}"
        lines.append(base)
    return "\n".join(lines)


class FilterSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#6a737d"))
        self.comment_format.setFontItalic(True)
        self.operator_format = QTextCharFormat()
        self.operator_format.setForeground(QColor("#005cc5"))
        self.operator_format.setFontWeight(QFont.Weight.Bold)
        self.invalid_format = QTextCharFormat()
        self.invalid_format.setForeground(QColor("#d73a49"))
        self.invalid_format.setUnderlineColor(QColor("#d73a49"))
        self.invalid_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        stripped = text.lstrip()
        if not stripped or stripped.startswith("#"):
            self.setFormat(0, len(text), self.comment_format)
            return
        if stripped.startswith(_OPERATORS):
            op_len = 1
            if len(stripped) > 1 and stripped[1] == " ":
                op_len = 2
            leading = len(text) - len(stripped)
            self.setFormat(leading, op_len, self.operator_format)
        else:
            # bare line -> interpreted as exclusion; mark as a hint
            pass
        # validate
        rule = _line_to_rule(text)
        if rule is not None:
            message = validate_rule(rule)
            if message:
                self.setFormat(0, len(text), self.invalid_format)


class FilterEditorDialog(QDialog):
    def __init__(self, rules=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rsync include/exclude filters")
        self.resize(760, 520)

        if rules is None:
            rules = []
        text = _rules_to_text(list(rules))
        if not text.strip():
            text = _EXAMPLE_TEXT

        self.editor = QPlainTextEdit(self)
        self.text_edit = self.editor
        self.plain_text_edit = self.editor
        self.text_editor = self.editor
        self.editor.setPlainText(text)
        self.highlighter = FilterSyntaxHighlighter(self.editor.document())

        self.preview_label = QLabel("", self)
        self.preview_label.setWordWrap(True)
        self.editor.cursorPositionChanged.connect(self._update_preview)
        self._update_preview()

        import_button = QPushButton("Import", self)
        export_button = QPushButton("Export", self)
        help_button = QPushButton("Help", self)
        import_button.clicked.connect(self._import)
        export_button.clicked.connect(self._export)
        help_button.clicked.connect(self._show_help)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(import_button)
        button_row.addWidget(export_button)
        button_row.addWidget(help_button)
        button_row.addStretch(1)
        button_row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.preview_label)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def rules(self) -> list[FilterRule]:
        result: list[FilterRule] = []
        for line in self.editor.toPlainText().splitlines():
            rule = _line_to_rule(line)
            if rule is not None:
                result.append(rule)
        return result

    def get_rules(self) -> list[FilterRule]:
        return self.rules()

    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, value: str) -> None:
        self.editor.setPlainText(value)

    def toPlainText(self) -> str:  # noqa: N802
        return self.editor.toPlainText()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _update_preview(self) -> None:
        cursor = self.editor.textCursor()
        block = cursor.block()
        line = block.text()
        stripped = line.strip()
        if not stripped:
            self.preview_label.setText("Preview: (blank line, ignored)")
            return
        if stripped.startswith("#"):
            self.preview_label.setText("Preview: comment, ignored")
            return
        if stripped.startswith(_OPERATORS):
            self.preview_label.setText(f"Preview: advanced rsync rule: {stripped}")
        else:
            self.preview_label.setText(f"Preview: interpreted as exclusion: - {stripped}")

    def _has_errors(self) -> bool:
        for line in self.editor.toPlainText().splitlines():
            rule = _line_to_rule(line)
            if rule is not None and validate_rule(rule):
                return True
        return False

    def _show_help(self) -> None:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QPlainTextEdit as _QPlainTextEdit

        dialog = QDialog(self)
        dialog.setWindowTitle("Rsync filters")
        dialog.resize(640, 520)
        layout = QVBoxLayout(dialog)
        viewer = _QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        viewer.setPlainText(_RSFILTER_HELP)
        layout.addWidget(viewer, 1)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(dialog.reject)
        layout.addWidget(close_buttons)
        dialog.exec()

    def _import(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import rsync filter file")
        if name:
            try:
                self.editor.setPlainText(Path(name).read_text(encoding="utf-8"))
            except OSError as exc:
                QMessageBox.warning(self, "Import failed", str(exc))

    def _export(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export rsync filter file")
        if name:
            try:
                Path(name).write_text(self.editor.toPlainText(), encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Export failed", str(exc))

    def _accept_if_valid(self) -> None:
        if self._has_errors():
            QMessageBox.warning(
                self, "Invalid filters", "Correct the highlighted filter lines first."
            )
            return
        self.accept()

    # Backwards-compatible alias used by the old table implementation.
    def _accept(self) -> None:
        self._accept_if_valid()


# Keep the old delegate importable for compatibility.
class FilterTypeDelegate:
    """Deprecated: retained only so old imports keep working."""

    def __init__(self, parent=None) -> None:
        self.parent = parent


def deepcopy_rules(rules):
    return deepcopy(rules)
