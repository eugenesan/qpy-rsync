from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.enums import DeleteTiming, EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile


def profile() -> SyncProfile:
    return SyncProfile(name="test", source=Endpoint(EndpointKind.LOCAL, "/src/"), destination=Endpoint(EndpointKind.LOCAL, "/dst/"))


def test_compare_is_dry_run_and_uses_argument_vector() -> None:
    spec = build_compare_spec(profile())
    assert spec.program == "rsync"
    assert "--dry-run" in spec.arguments
    assert spec.arguments[-3:] == ("--", "/src/", "/dst/")
    assert spec.environment == {"LC_ALL": "C"}


def test_fuzzy_delete_forces_delete_after() -> None:
    item = profile()
    item.transfer.fuzzy = True
    item.transfer.delete = True
    item.transfer.delete_timing = DeleteTiming.BEFORE
    spec = build_sync_spec(item)
    assert "--fuzzy" in spec.arguments
    assert "--delete-after" in spec.arguments
    assert "--delete-before" not in spec.arguments
