#!/bin/sh
# Run qpy-rsync from a source checkout with system Python and system PySide6.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${QPY_RSYNC_SYSTEM_PYTHON:-/usr/bin/python3}
if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "qpy-rsync: system Python is not executable: $PYTHON" >&2
    exit 127
fi
if [ ! -d "$SCRIPT_DIR/src/qpy_rsync" ]; then
    printf '%s\n' "qpy-rsync: cannot find src/qpy_rsync below $SCRIPT_DIR" >&2
    exit 2
fi
if ! "$PYTHON" -c 'import PySide6' >/dev/null 2>&1; then
    cat >&2 <<'EOF'
qpy-rsync: system Python cannot import PySide6.
Install the Ubuntu PySide6 runtime packages listed in docs/installation.md.
EOF
    exit 1
fi
unset VIRTUAL_ENV PYENV_VERSION PYTHONHOME PYTHONPATH
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
unset QML2_IMPORT_PATH QML_IMPORT_PATH LD_LIBRARY_PATH
export PYTHONPATH="$SCRIPT_DIR/src"
exec "$PYTHON" -m qpy_rsync.app "$@"
