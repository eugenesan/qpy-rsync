import pytest

from qpy_rsync.core.endpoints import parse_endpoint
from qpy_rsync.core.enums import EndpointKind


def test_local_directory_is_expanded_and_gets_trailing_slash(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/tester")
    endpoint = parse_endpoint("~/data")
    assert endpoint.kind is EndpointKind.LOCAL
    assert endpoint.rsync_operand() == "/home/tester/data/"


def test_ssh_endpoint_uses_remote_shell_syntax_and_trailing_slash() -> None:
    endpoint = parse_endpoint("alice@server:/srv/data")
    assert endpoint.kind is EndpointKind.SSH
    assert endpoint.user == "alice"
    assert endpoint.host == "server"
    assert endpoint.rsync_operand() == "alice@server:/srv/data/"


def test_ssh_alias_without_user_is_supported() -> None:
    assert parse_endpoint("nas:/backup").rsync_operand() == "nas:/backup/"


def test_daemon_and_ambiguous_remote_syntax_are_rejected() -> None:
    with pytest.raises(ValueError, match="daemon"):
        parse_endpoint("server::module")
    with pytest.raises(ValueError, match="absolute"):
        parse_endpoint("server:relative")
