#!/bin/sh
# Run qpy-rsync tests and validation with system Python, without .venv.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${QPY_RSYNC_SYSTEM_PYTHON:-/usr/bin/python3}
if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "qpy-rsync-test: system Python is not executable: $PYTHON" >&2
    exit 127
fi
if [ ! -d "$SCRIPT_DIR/src/qpy_rsync" ] || [ ! -d "$SCRIPT_DIR/tests" ]; then
    printf '%s\n' "qpy-rsync-test: incomplete source checkout below $SCRIPT_DIR" >&2
    exit 2
fi
if ! "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
    cat >&2 <<'EOF'
qpy-rsync-test: system Python cannot import pytest.
On Ubuntu, install python3-pytest. See docs/installation.md.
EOF
    exit 1
fi
unset VIRTUAL_ENV PYENV_VERSION PYTHONHOME PYTHONPATH
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
unset QML2_IMPORT_PATH QML_IMPORT_PATH LD_LIBRARY_PATH
export PYTHONPATH="$SCRIPT_DIR/src"
cd "$SCRIPT_DIR"
"$PYTHON" -m pytest "$@"
"$PYTHON" -m compileall -q src
git diff --check
