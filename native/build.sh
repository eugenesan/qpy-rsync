#!/usr/bin/env bash
# Experimental native extension build. Does not touch the runtime app.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${QPY_NATIVE_BUILD_DIR:-/tmp/opencode/qpy-native-build}
PYTHON=${QPY_RSYNC_SYSTEM_PYTHON:-/usr/bin/python3}
cmake -S "$ROOT/native" -B "$BUILD" -DPYTHON_EXECUTABLE="$PYTHON" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j2
OUT=${QPY_NATIVE_OUTPUT:-$ROOT/src/qpy_rsync/_qpy_native.so}
cp "$BUILD"/_qpy_native*.so "$OUT"
printf 'built %s\n' "$OUT"
