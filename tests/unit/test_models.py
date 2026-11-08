from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint


def test_local_operand_is_plain_path() -> None:
    assert Endpoint(EndpointKind.LOCAL, "/tmp/source").rsync_operand() == "/tmp/source"


def test_ssh_operand_includes_user_and_host() -> None:
    endpoint = Endpoint(EndpointKind.SSH, "/srv/data", host="example.test", user="alice")
    assert endpoint.rsync_operand() == "alice@example.test:/srv/data"


def test_local_operand_expands_home(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/tester")
    assert Endpoint(EndpointKind.LOCAL, "~/data").rsync_operand() == "/home/tester/data"
