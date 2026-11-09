from pathlib import Path


def test_sync_fixture_scripts_exist_and_are_executable() -> None:
    root = Path(__file__).parents[2]
    for name in ("setup-sync-smoke-test.sh", "collect-sync-smoke-results.sh"):
        path = root / "tools" / name
        assert path.exists()
        assert path.stat().st_mode & 0o111
