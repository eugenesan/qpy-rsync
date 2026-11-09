from pathlib import Path

from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.core.enums import EndpointKind, FilterRuleType
from qpy_rsync.core.models import Endpoint, FilterRule, SyncProfile


def test_decision_merge_filter_precedes_user_filters(tmp_path: Path) -> None:
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    profile.filters = [FilterRule("*.tmp", rule_type=FilterRuleType.EXCLUDE)]
    filter_file = tmp_path / "decisions.rules"
    filter_file.write_text("- /skip\n", encoding="utf-8")
    arguments = list(build_compare_spec(profile, filter_file=filter_file).arguments)
    assert arguments.index(f"--filter=merge {filter_file}") < arguments.index("--exclude=*.tmp")
