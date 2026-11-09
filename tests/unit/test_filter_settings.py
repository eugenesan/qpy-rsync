import pytest

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
from qpy_rsync.gui.filter_settings import decode_filters, encode_filters


def test_filter_settings_round_trip() -> None:
    rules = [
        FilterRule("/.git/", rule_type=FilterRuleType.INCLUDE, comment="traverse"),
        FilterRule("*.tmp", enabled=False, rule_type=FilterRuleType.EXCLUDE),
    ]
    assert decode_filters(encode_filters(rules)) == rules


def test_filter_settings_reject_non_list_payload() -> None:
    with pytest.raises(ValueError, match="list"):
        decode_filters('{"rule": "*.tmp"}')
