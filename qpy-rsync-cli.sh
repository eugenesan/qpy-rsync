#!/bin/sh
# Run qpy-rsync-cli from a source checkout with system Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${QPY_RSYNC_SYSTEM_PYTHON:-/usr/bin/python3}
if [ ! -x "$PYTHON" ]; then
    printf '%s\n' "qpy-rsync-cli: system Python is not executable: $PYTHON" >&2
    exit 127
fi
if [ ! -d "$SCRIPT_DIR/src/qpy_rsync" ]; then
    printf '%s\n' "qpy-rsync-cli: cannot find src/qpy_rsync below $SCRIPT_DIR" >&2
    exit 2
fi
unset VIRTUAL_ENV PYENV_VERSION PYTHONHOME PYTHONPATH
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
unset QML2_IMPORT_PATH QML_IMPORT_PATH LD_LIBRARY_PATH
export PYTHONPATH="$SCRIPT_DIR/src"
exec "$PYTHON" -m qpy_rsync.cli "$@"
