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
# Keep the desktop's own Qt style/theme (for example KDE Breeze). The KDE
# platform theme loads Qt Quick, which tries to create an OpenGL context; remote
# X11 sessions often expose neither GLX nor EGL. Disabling the XCB GL
# integration keeps the platform theme intact and lets Qt Quick fall back to its
# software renderer. app.py filters the resulting known warnings.
export QT_XCB_GL_INTEGRATION=none
export QT_QUICK_BACKEND=software
export QSG_RHI_BACKEND=software
export PYTHONPATH="$SCRIPT_DIR/src"
exec "$PYTHON" -m qpy_rsync.app "$@"
