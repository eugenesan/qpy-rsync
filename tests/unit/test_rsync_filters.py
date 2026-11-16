from qpy_rsync.backend.rsync_filters import validate_rule
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
def test_validate_classic_and_advanced_rules():
    assert not validate_rule(FilterRule("*.tmp",rule_type=FilterRuleType.EXCLUDE)); assert not validate_rule(FilterRule("- *.tmp",rule_type=FilterRuleType.ADVANCED)); assert validate_rule(FilterRule("*.tmp",rule_type=FilterRuleType.ADVANCED))

def test_validate_all_advanced_rsync_rules():
    valid = (
        "-s *.kate-swp", "-p *.o", "+r keep/", "-! */", "-/ /etc/passwd",
        "H *.tmp", "S cache/", "P keep/", "R temp/", ". rules.txt",
        ": .rsync-filter", "dir-merge,n- .rsync-filter", "clear", "!",
        "exclude *.log", "merge /etc/rsync/default.rules",
    )
    for value in valid:
        assert not validate_rule(FilterRule(value, rule_type=FilterRuleType.ADVANCED)), value
    for value in ("bogus pattern", "-z foo", "-s", "merge"):
        assert validate_rule(FilterRule(value, rule_type=FilterRuleType.ADVANCED)), value
