from __future__ import annotations
from typing import Any
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from qpy_rsync.backend.rsync_filters import validate_rule
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule

class FilterRuleModel(QAbstractTableModel):
    ENABLED, TYPE, RULE, COMMENT, STATUS = range(5)
    HEADERS = ("Enabled", "Type", "Pattern or rule", "Comment", "Status")
    def __init__(self, rules: list[FilterRule] | None = None, parent: object | None = None) -> None:
        super().__init__(parent); self.rules = list(rules or [])
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int: return 0 if parent.isValid() else len(self.rules)
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int: return len(self.HEADERS)
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole) -> Any:
        return self.HEADERS[section] if orientation is Qt.Orientation.Horizontal and role is Qt.ItemDataRole.DisplayRole else None
    def data(self, index, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rules): return None
        rule = self.rules[index.row()]
        if role is Qt.ItemDataRole.CheckStateRole and index.column() == self.ENABLED: return Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return {self.TYPE: rule.rule_type.value, self.RULE: rule.rule, self.COMMENT: rule.comment, self.STATUS: validate_rule(rule) or "OK"}.get(index.column())
        return None
    def flags(self, index):
        flags = super().flags(index)
        if index.column() == self.ENABLED: return flags | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() in (self.TYPE, self.RULE, self.COMMENT): return flags | Qt.ItemFlag.ItemIsEditable
        return flags
    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid(): return False
        rule = self.rules[index.row()]
        if role is Qt.ItemDataRole.CheckStateRole and index.column() == self.ENABLED: rule.enabled = Qt.CheckState(value) is Qt.CheckState.Checked
        elif role is Qt.ItemDataRole.EditRole and index.column() == self.TYPE: rule.rule_type = FilterRuleType(str(value))
        elif role is Qt.ItemDataRole.EditRole and index.column() == self.RULE: rule.rule = str(value).strip()
        elif role is Qt.ItemDataRole.EditRole and index.column() == self.COMMENT: rule.comment = str(value)
        else: return False
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.STATUS)); return True
    def add_rule(self, rule):
        row=len(self.rules); self.beginInsertRows(QModelIndex(),row,row); self.rules.append(rule); self.endInsertRows()
    def remove_row(self,row):
        if 0<=row<len(self.rules): self.beginRemoveRows(QModelIndex(),row,row); del self.rules[row]; self.endRemoveRows()
    def move_row(self,row,delta):
        target=row+delta
        if 0<=row<len(self.rules) and 0<=target<len(self.rules): self.beginResetModel(); self.rules[row],self.rules[target]=self.rules[target],self.rules[row]; self.endResetModel(); return target
        return row
    def replace_rules(self,rules): self.beginResetModel(); self.rules=list(rules); self.endResetModel()
    def has_errors(self): return any(rule.enabled and validate_rule(rule) for rule in self.rules)
