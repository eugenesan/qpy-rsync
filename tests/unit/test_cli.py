from argparse import Namespace

from qpy_rsync.backend.process_runner import ProcessResult
from qpy_rsync.cli import main, profile_from_args
from qpy_rsync.core.enums import SyncMode


def args(**overrides):
    values = {
        "dir_pair": ["/src/", "/dst/"],
        "backup": "",
        "mode": "update",
        "compare": True,
        "json": False,
        "show_command": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_profile_from_cli_arguments() -> None:
    profile = profile_from_args(
        args(backup="/recovery", mode="mirror")
    )
    assert profile.source.path == "/src/"
    assert profile.destination.path == "/dst/"
    assert profile.backup.directory == "/recovery"
    assert profile.transfer.sync_mode is SyncMode.MIRROR


def test_compare_prints_normalized_actions(monkeypatch, capsys) -> None:
    record = ">f+++++++++|qpy-rsync|4|qpy-rsync|2026/01/01-00:00:00|qpy-rsync|new.txt\n"
    monkeypatch.setattr(
        "qpy_rsync.cli.run_process",
        lambda _spec: __import__("subprocess").CompletedProcess([], 0, record, ""),
    )
    assert main(["--dir-pair", "/src/", "/dst/", "--mode", "update", "--compare"]) == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "new.txt" in output


def test_json_compare_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "qpy_rsync.cli.run_process",
        lambda _spec: __import__("subprocess").CompletedProcess([], 0, "", ""),
    )
    assert main(["--dir-pair", "/src/", "/dst/", "--mode", "new-only", "--compare", "--json"]) == 0
    output = capsys.readouterr().out
    assert '"mode": "new_only"' in output
    assert '"changes": []' in output


def test_nonzero_rsync_status_is_returned(monkeypatch) -> None:
    monkeypatch.setattr(
        "qpy_rsync.cli.run_process",
        lambda _spec: __import__("subprocess").CompletedProcess([], 23, "", "partial"),
    )
    assert main(["--dir-pair", "/src/", "/dst/", "--compare"]) == 23
