from qpy_rsync.backend.rsync_filters import validate_rule
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
def test_validate_classic_and_advanced_rules():
    assert not validate_rule(FilterRule("*.tmp",rule_type=FilterRuleType.EXCLUDE)); assert not validate_rule(FilterRule("- *.tmp",rule_type=FilterRuleType.ADVANCED)); assert validate_rule(FilterRule("*.tmp",rule_type=FilterRuleType.ADVANCED))
