from PySide6.QtCore import Qt
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
from qpy_rsync.gui.filter_rule_model import FilterRuleModel
def test_rule_model_edits_type_and_reorders():
    model=FilterRuleModel([FilterRule("*.tmp",rule_type=FilterRuleType.EXCLUDE),FilterRule("/docs/***",rule_type=FilterRuleType.INCLUDE)]); assert model.setData(model.index(1,model.TYPE),"exclude",Qt.ItemDataRole.EditRole); assert model.rules[1].rule_type is FilterRuleType.EXCLUDE; assert model.move_row(1,-1)==0
def test_invalid_enabled_advanced_rule_is_blocked():
    model=FilterRuleModel([FilterRule("invalid")]); assert model.has_errors(); model.rules[0].enabled=False; assert not model.has_errors()
