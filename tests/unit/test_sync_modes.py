from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind, SyncMode
from qpy_rsync.core.execution_plan import build_execution_plan
from qpy_rsync.core.models import Endpoint, SyncProfile, TransferOptions


def profile(mode: SyncMode) -> SyncProfile:
    return SyncProfile(
        "mode",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
        transfer=TransferOptions(sync_mode=mode),
    )


def test_update_retains_destination_only_inventory() -> None:
    item = profile(SyncMode.UPDATE)
    assert "--ignore-existing" not in build_sync_spec(item).arguments
    assert not any(arg.startswith("--delete-") for arg in build_sync_spec(item).arguments)
    change = Change("extra", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    plan = build_execution_plan(item, [change], ChangeDecisions())
    assert plan.summary.retained_destination_only == 1
    assert plan.summary.excluded == 0


def test_mirror_emits_delete_timing() -> None:
    args = build_sync_spec(profile(SyncMode.MIRROR)).arguments
    assert "--delete-during" in args


def test_new_only_emits_ignore_existing_without_delete() -> None:
    args = build_sync_spec(profile(SyncMode.NEW_ONLY)).arguments
    assert "--ignore-existing" in args
    assert not any(arg.startswith("--delete-") for arg in args)


def test_destination_only_is_selectable_but_defaults_to_keep() -> None:
    change = Change("extra", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    decisions = ChangeDecisions()
    assert decisions.selectable(change)
    assert decisions.effective(change).value == "exclude"

def test_string_mode_values_are_normalized() -> None:
    mirror = TransferOptions(sync_mode="mirror")  # type: ignore[arg-type]
    new_only = TransferOptions(sync_mode="new_only")  # type: ignore[arg-type]
    assert mirror.mirror_enabled
    assert not mirror.new_only_enabled
    assert new_only.new_only_enabled
    assert not new_only.mirror_enabled


def test_mirror_deletion_record_parses_as_delete() -> None:
    from qpy_rsync.backend.process_runner import ProcessResult
    from qpy_rsync.core.changes import ChangeAction
    from qpy_rsync.services.compare_service import CompareService

    service = CompareService()
    captured = []
    service.on_finished = captured.append
    service._delete_enabled = profile(SyncMode.MIRROR).transfer.mirror_enabled
    service._finish(
        ProcessResult(
            0,
            "*deleting  |qpy-rsync||qpy-rsync||qpy-rsync|extra.txt\n",
            "",
        )
    )
    assert captured[0].parsed.changes[0].action is ChangeAction.DELETE


def test_update_deletion_record_parses_as_destination_only() -> None:
    from qpy_rsync.backend.process_runner import ProcessResult
    from qpy_rsync.core.changes import ChangeAction
    from qpy_rsync.services.compare_service import CompareService

    service = CompareService()
    captured = []
    service.on_finished = captured.append
    service._delete_enabled = profile(SyncMode.UPDATE).transfer.mirror_enabled
    service._finish(
        ProcessResult(
            0,
            "*deleting  |qpy-rsync||qpy-rsync||qpy-rsync|extra.txt\n",
            "",
        )
    )
    assert captured[0].parsed.changes[0].action is ChangeAction.DESTINATION_ONLY

