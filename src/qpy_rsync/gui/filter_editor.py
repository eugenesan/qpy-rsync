from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QFileDialog,QHBoxLayout,QInputDialog,QMessageBox,QPushButton,QTableView,QVBoxLayout
from qpy_rsync.backend.rsync_filters import export_filter_file,import_filter_file
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
from .filter_rule_model import FilterRuleModel
class FilterEditorDialog(QDialog):
    def __init__(self,rules,parent=None):
        super().__init__(parent); self.setWindowTitle("Rsync include/exclude filters"); self.resize(900,430); self.model=FilterRuleModel(deepcopy(rules),self); self.table=QTableView(self); self.table.setModel(self.model); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        controls=QHBoxLayout()
        for label,callback in (("Add Include",lambda:self._add(FilterRuleType.INCLUDE)),("Add Exclude",lambda:self._add(FilterRuleType.EXCLUDE)),("Add Advanced",lambda:self._add(FilterRuleType.ADVANCED)),("Duplicate",self._duplicate),("Remove",self._remove),("Move Up",lambda:self._move(-1)),("Move Down",lambda:self._move(1)),("Import...",self._import),("Export...",self._export)):
            button=QPushButton(label); button.clicked.connect(callback); controls.addWidget(button)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._accept_if_valid); buttons.rejected.connect(self.reject); layout=QVBoxLayout(self); layout.addWidget(self.table); layout.addLayout(controls); layout.addWidget(buttons)
    def rules(self): return deepcopy(self.model.rules)
    def _selected_row(self):
        rows=self.table.selectionModel().selectedRows(); return rows[0].row() if rows else -1
    def _add(self,rule_type):
        label="Complete rsync filter rule:" if rule_type is FilterRuleType.ADVANCED else "Rsync pattern:"; value,accepted=QInputDialog.getText(self,f"Add {rule_type.value}",label)
        if accepted and value.strip(): self.model.add_rule(FilterRule(value.strip(),rule_type=rule_type))
    def _duplicate(self):
        row=self._selected_row()
        if row>=0:self.model.add_rule(deepcopy(self.model.rules[row]))
    def _remove(self): self.model.remove_row(self._selected_row())
    def _move(self,delta): self.table.selectRow(self.model.move_row(self._selected_row(),delta))
    def _import(self):
        name,_=QFileDialog.getOpenFileName(self,"Import rsync filter file")
        if name:self.model.replace_rules(import_filter_file(Path(name)))
    def _export(self):
        name,_=QFileDialog.getSaveFileName(self,"Export rsync filter file")
        if name:export_filter_file(Path(name),self.model.rules)
    def _accept_if_valid(self):
        if self.model.has_errors(): QMessageBox.warning(self,"Invalid filters","Correct enabled filter errors first.")
        else:self.accept()
