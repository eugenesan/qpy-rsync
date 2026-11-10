from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "tools/run-sync-smoke-test.sh"


def test_guided_sync_runner_exists_and_is_executable() -> None:
    assert RUNNER.exists()
    assert RUNNER.stat().st_mode & 0o111


def test_guided_sync_runner_help() -> None:
    result = subprocess.run(
        [str(RUNNER), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "update [default|manual-delete]" in result.stdout
    assert "mirror [default|protect-one]" in result.stdout
    assert "new-only [default|manual-delete]" in result.stdout
