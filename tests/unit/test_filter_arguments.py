from qpy_rsync.backend.filter_arguments import filter_arguments
from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.core.enums import EndpointKind, FilterRuleType
from qpy_rsync.core.models import Endpoint, FilterRule, SyncProfile


def test_mixed_filter_order_reaches_command_vector() -> None:
    profile = SyncProfile(
        name="filters",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    profile.filters = [
        FilterRule("/.git/", rule_type=FilterRuleType.INCLUDE),
        FilterRule("/.git/HEAD", rule_type=FilterRuleType.INCLUDE),
        FilterRule("/.git/***", rule_type=FilterRuleType.EXCLUDE),
        FilterRule("- *.tmp", rule_type=FilterRuleType.ADVANCED),
        FilterRule("*.bak", enabled=False, rule_type=FilterRuleType.EXCLUDE),
    ]
    expected = [
        "--include=/.git/",
        "--include=/.git/HEAD",
        "--exclude=/.git/***",
        "--filter",
        "- *.tmp",
    ]
    assert filter_arguments(profile.filters) == expected
    arguments = list(build_compare_spec(profile).arguments)
    start = arguments.index(expected[0])
    assert arguments[start : start + len(expected)] == expected
