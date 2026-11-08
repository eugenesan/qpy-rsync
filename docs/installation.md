# Installation and host setup

qpy-rsync can run with either Ubuntu's system Python packages or an isolated
`.venv`. The virtual environment is optional.

## Runtime requirements

qpy-rsync currently targets Linux with Python 3.11 or newer and requires:

- Python 3
- PySide6 with Qt Core, GUI, and Widgets
- rsync 3.x
- OpenSSH client for SSH endpoints
- `setsid` from util-linux for remote operations
- a graphical SSH askpass helper when password or key-passphrase prompting is
  required; KDE Plasma users can use `ksshaskpass`

On Ubuntu 26.04, install the runtime packages with:

```bash
sudo apt update
sudo apt install \
  python3 \
  python3-pyside6.qtcore \
  python3-pyside6.qtgui \
  python3-pyside6.qtwidgets \
  rsync \
  openssh-client \
  util-linux \
  ksshaskpass
```

Package names can vary on other Ubuntu releases. Inspect available PySide6
packages with:

```bash
apt-cache search '^python3-pyside6'
```

## Run from a source checkout without `.venv`

The repository uses the `src/` layout, so the checkout is not importable by
system Python unless it is installed or `src` is added to `PYTHONPATH`.

From the repository root, use the runner:

```bash
./qpy-rsync.sh
```

The equivalent direct command is:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 -m qpy_rsync.app
```

Run tests with system Python:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest -q
```

Verify that the application uses Ubuntu's PySide6 rather than a virtual
environment:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 - <<'PY'
import sys
import PySide6
from PySide6.QtCore import qVersion

print("Python:", sys.executable)
print("PySide6:", PySide6.__file__)
print("Qt:", qVersion())
PY
```

The Python executable should be `/usr/bin/python3`, and PySide6 should normally
resolve below `/usr/lib/python3/dist-packages`.

## Optional `.venv` workflow

A virtual environment remains useful for development against a PyPI PySide6
release:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest -q
qpy-rsync
```

Do not use `sudo pip` to install into Ubuntu's system Python. Use APT packages,
a virtual environment, or a future qpy-rsync Debian package.

## Development packages

For system-Python development on Ubuntu 26.04:

```bash
sudo apt install \
  python3-pytest \
  python3-pytest-cov \
  mypy
```

Ruff is optional and is not a runtime dependency. If it is unavailable from the
Ubuntu repositories, install it separately with `pipx`, use its standalone
binary, or keep it in a development `.venv`.

Typical validation commands are:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest -q
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest --cov=qpy_rsync
PYTHONPATH="$PWD/src" /usr/bin/python3 -m mypy src/qpy_rsync
/usr/bin/python3 -m compileall -q src

git diff --check
```

Run Ruff only when available:

```bash
if command -v ruff >/dev/null; then
  ruff check .
fi
```

## SSH authentication

qpy-rsync delegates authentication and host-key handling to OpenSSH. For remote
operations it uses the system askpass helper and restores the active X11
`DISPLAY` in rsync's remote-shell command.

Recommended SSH setup:

1. Verify the connection manually with `ssh user@host`.
2. Review and accept the host key using OpenSSH's normal prompt.
3. Prefer a key loaded into `ssh-agent`.
4. Install `ksshaskpass` when graphical password or key-passphrase prompting is
   required on KDE Plasma.

Debug a launch with:

```bash
QPY_RSYNC_DEBUG=1 ./qpy-rsync.sh 2>&1 | tee qpy-rsync-debug.log
```

Review the log before sharing it because endpoint paths, host names, and desktop
session paths can appear in diagnostics.
