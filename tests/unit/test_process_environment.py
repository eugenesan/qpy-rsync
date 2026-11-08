from qpy_rsync.backend.process_runner import sanitize_process_environment


class FakeEnvironment:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)

    def remove(self, name: str) -> None:
        self.values.pop(name, None)


def test_python_and_qt_runtime_paths_are_removed() -> None:
    environment = FakeEnvironment(
        {
            "DISPLAY": ":0",
            "XAUTHORITY": "/run/user/1000/xauth_test",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "SSH_AUTH_SOCK": "/run/user/1000/ssh-agent.socket",
            "LANG": "en_US.UTF-8",
            "QT_PLUGIN_PATH": "/venv/PySide6/plugins",
            "QT_QPA_PLATFORM_PLUGIN_PATH": "/venv/PySide6/plugins/platforms",
            "QML2_IMPORT_PATH": "/venv/PySide6/qml",
            "QML_IMPORT_PATH": "/venv/PySide6/qml",
            "LD_LIBRARY_PATH": "/venv/PySide6/Qt/lib",
            "PYTHONHOME": "/venv",
            "PYTHONPATH": "/checkout/src",
        }
    )

    sanitize_process_environment(environment)

    assert environment.values == {
        "DISPLAY": ":0",
        "XAUTHORITY": "/run/user/1000/xauth_test",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "SSH_AUTH_SOCK": "/run/user/1000/ssh-agent.socket",
        "LANG": "en_US.UTF-8",
    }
