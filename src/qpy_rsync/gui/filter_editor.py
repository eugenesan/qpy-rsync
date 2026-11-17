from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.rsync_filters import (
    export_filter_file,
    import_filter_file,
    is_advanced_rule,
    parse_advanced_rule,
    validate_rule,
)
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
  H pattern   hide (sender-only exclude)
  S pattern   show (sender-only include)
  . file      merge a rule file once
  : file      merge a per-directory rule file
  !           clear the current list of rules
  (no prefix) treated as an exclusion: "- pattern"

Long names work too: exclude, include, protect, risk, hide, show,
merge, dir-merge and clear.

Modifiers may follow the operator (with or without a comma), for example:
  -s pattern   sender-side exclude: ignore on source, do not protect on dest
  -p pattern   perishable exclude (does not block deleting empty dirs)
  -r pattern   receiver-side exclude (protects from deletion)
  +r pattern   receiver-side include (allows deletion)
  -/ pattern   match against the absolute path
  -! pattern   apply the rule when the pattern does NOT match
  dir-merge,n- .rsync-filter
With Mirror mode, "-s *.kate-swp" ignores those files on the source while
letting --delete remove them from the destination.

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
    if is_advanced_rule(stripped):
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
        self.invalid_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.SingleUnderline
        )

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        stripped = text.lstrip()
        if not stripped or stripped.startswith("#"):
            self.setFormat(0, len(text), self.comment_format)
            return
        parsed = parse_advanced_rule(stripped)
        if parsed is not None:
            token = parsed[0]
            leading = len(text) - len(stripped)
            self.setFormat(leading, len(token), self.operator_format)
        rule = _line_to_rule(text)
        if rule is not None and validate_rule(rule):
            self.setFormat(0, len(text), self.invalid_format)


class _RulePreview(QPlainTextEdit):
    """The rule explanation box: two lines by default, manually resizable."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(80, self.fontMetrics().height() * 2 + 6)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, self.fontMetrics().height() * 2 + 6)


class _LineNumberArea(QWidget):
    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor)
        self.editor = editor
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.Base)

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event: object) -> None:  # noqa: N802
        editor = self.editor
        painter = QPainter(self)
        try:
            palette = self.palette()
            painter.fillRect(
                self.rect(), palette.color(self.backgroundRole())
            )
            painter.setFont(editor.font())
            painter.setPen(palette.color(palette.ColorRole.Text))
            layout = editor.document().documentLayout()
            block = editor.firstVisibleBlock()
            rect = layout.blockBoundingRect(block)
            top = int(rect.top() - editor.contentOffset().y())
            height = int(rect.height())
            number = block.blockNumber() + 1
            while block.isValid() and top <= self.height():
                if block.isVisible() and top + height >= 0:
                    painter.drawText(
                        0,
                        top,
                        editor.line_number_width() - 4,
                        height,
                        Qt.AlignmentFlag.AlignRight,
                        str(number),
                    )
                block = block.next()
                if not block.isValid():
                    break
                top += height
                height = int(layout.blockBoundingRect(block).height())
                number += 1
        finally:
            painter.end()


class _NumberedTextEdit(QPlainTextEdit):
    """A plain text editor with a line-number gutter."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._numbers = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter)
        self.updateRequest.connect(self._update_gutter_area)
        self._update_gutter()

    def line_number_width(self) -> int:
        digits = max(1, len(str(max(1, self.blockCount()))))
        return self.fontMetrics().horizontalAdvance("0") * digits + 12

    def _update_gutter(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter_area(self, rect, dy: int) -> None:
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(
                0, rect.y(), self._numbers.width(), rect.height()
            )

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._numbers.setGeometry(
            0, 0, self.line_number_width(), self.height()
        )


class FilterEditorWidget(QWidget):
    """The text editor and its preview, usable standalone or in a dialog."""

    def __init__(self, rules=None, parent=None, text: str | None = None) -> None:
        super().__init__(parent)
        if text is None:
            text = _rules_to_text(list(rules or []))
        if not text.strip():
            text = _EXAMPLE_TEXT
        self.editor = _NumberedTextEdit(self)
        self.text_edit = self.editor
        self.plain_text_edit = self.editor
        self.text_editor = self.editor
        self.editor.setPlainText(text)
        self.highlighter = FilterSyntaxHighlighter(self.editor.document())
        self.preview_label = _RulePreview(self)
        self.preview_label.setReadOnly(True)
        self.preview_label.setPlaceholderText("Line preview")
        self.editor.cursorPositionChanged.connect(self._update_preview)
        self._update_preview()
        button_row = QHBoxLayout()
        self.import_button = QPushButton("Import", self)
        self.export_button = QPushButton("Export", self)
        self.help_button = QPushButton("Help", self)
        self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        self.help_button.clicked.connect(self.show_help)
        button_row.addWidget(self.import_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.help_button)
        button_row.addStretch(1)
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview_label)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(1, False)
        two_lines = self.preview_label.fontMetrics().height() * 2 + 8
        splitter.setSizes([360, two_lines])
        self.splitter = splitter
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(button_row)

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

    def first_error(self) -> tuple[int, str] | None:
        for number, line in enumerate(self.text().splitlines(), 1):
            rule = _line_to_rule(line)
            if rule is not None:
                message = validate_rule(rule)
                if message:
                    return number, message
        return None

    def has_errors(self) -> bool:
        return self.first_error() is not None

    def _update_preview(self) -> None:
        line = self.editor.textCursor().block().text()
        number = self.editor.textCursor().blockNumber() + 1
        stripped = line.strip()
        if not stripped:
            text = f"Line {number}: blank, ignored"
        elif stripped.startswith("#"):
            text = f"Line {number}: comment, ignored"
        elif is_advanced_rule(stripped):
            text = f"Line {number}: rsync rule: {stripped}"
        else:
            text = f"Line {number}: exclusion: - {stripped}"
        rule = _line_to_rule(line)
        if rule is not None:
            message = validate_rule(rule)
            if message:
                text = f"Line {number}: ERROR: {message}"
        self.preview_label.setPlainText(text)
        self.preview_label.setToolTip(text)

    def reveal_error(self) -> None:
        error = self.first_error()
        if error is None:
            return
        number, _message = error
        block = self.editor.document().findBlockByLineNumber(number - 1)
        cursor = self.editor.textCursor()
        cursor.setPosition(block.position())
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self._update_preview()

    def show_help(self) -> None:
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

    def import_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import rsync filter file")
        if name:
            try:
                self.editor.setPlainText(Path(name).read_text(encoding="utf-8"))
            except OSError as exc:
                QMessageBox.warning(self, "Import failed", str(exc))

    def export_file(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export rsync filter file")
        if name:
            try:
                Path(name).write_text(self.editor.toPlainText(), encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Export failed", str(exc))


class FilterEditorDialog(QDialog):
    def __init__(self, rules=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rsync include/exclude filters")
        self.resize(760, 520)
        self.widget = FilterEditorWidget(rules, self)
        self.editor = self.widget.editor
        self.text_edit = self.editor
        self.plain_text_edit = self.editor
        self.text_editor = self.editor
        self.preview_label = self.widget.preview_label
        self._has_errors = self.widget.has_errors
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        widget_buttons = self.widget.findChildren(QHBoxLayout)
        if widget_buttons:
            widget_buttons[-1].addWidget(buttons)
        else:
            layout = QVBoxLayout(self)
            layout.addWidget(self.widget, 1)
            layout.addWidget(buttons)

    def rules(self) -> list[FilterRule]:
        return self.widget.rules()

    def get_rules(self) -> list[FilterRule]:
        return self.rules()

    def text(self) -> str:
        return self.widget.text()

    def set_text(self, value: str) -> None:
        self.widget.set_text(value)

    def toPlainText(self) -> str:  # noqa: N802
        return self.widget.text()

    def _accept_if_valid(self) -> None:
        error = self.widget.first_error()
        if error is not None:
            self.widget.reveal_error()
            QMessageBox.warning(
                self,
                "Invalid filters",
                f"Line {error[0]}: {error[1]}\n\nCorrect the highlighted line first.",
            )
            return
        self.accept()

    def _accept(self) -> None:
        self._accept_if_valid()

    def _show_help(self) -> None:
        self.widget.show_help()

    def _import(self) -> None:
        self.widget.import_file()

    def _export(self) -> None:
        self.widget.export_file()


class FilterTypeDelegate:
    """Deprecated: retained only so old imports keep working."""

    def __init__(self, parent=None) -> None:
        self.parent = parent


def deepcopy_rules(rules):
    return deepcopy(rules)
