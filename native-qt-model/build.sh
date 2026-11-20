#!/usr/bin/env bash
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${QPY_QT_BUILD_DIR:-/tmp/opencode/qpy-qt-model-build}
cmake -S "$ROOT/native-qt-model" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD"
printf 'built %s/native_qt_model\n' "$BUILD"
