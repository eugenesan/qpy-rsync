#!/usr/bin/env bash
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${QPY_HYBRID_BUILD_DIR:-/tmp/opencode/qpy-hybrid-build}
PYTHON=${QPY_RSYNC_SYSTEM_PYTHON:-/usr/bin/python3}
cmake -S "$ROOT/native-hybrid" -B "$BUILD" -G Ninja \
  -DPYTHON_EXECUTABLE="$PYTHON" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD"
cp "$BUILD"/native_hybrid*.so "$ROOT/src/qpy_rsync/native_hybrid.so"
printf 'built %s\n' "$ROOT/src/qpy_rsync/native_hybrid.so"
