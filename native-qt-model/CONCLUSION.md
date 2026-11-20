# Native Qt model experiment — conclusion

Four steps were planned and all four have been measured. The short answer:
**the hybrid architecture is viable and worth prototyping in the real
application.** The earlier nanobind-kernel experiment could not improve the
application because it left the Python model/view adapter in place. This
experiment removes that adapter, and the measured numbers are decisive.

## Step 1 — native ceiling (standalone C++ app)

`native_qt_model`, 1M and 1.5M rows, three table panes plus an overview tree,
X11 at `:50` and offscreen. Full table in [README.md](README.md).

| | Result |
|---|---:|
| first paint, 4 panes | 12–17 ms |
| full reset with a new dataset | 141–208 ms |
| overview build, 30k folders | 25–36 ms |
| sort + paint | 55–886 ms (X11 variance) |
| 10 × scroll to row 100k+ | 324–972 ms |
| resident memory at 1M rows | 137 MB |

Compare with the Python implementation: **12–23 s** for `view.set_changes` at
520k rows, and ~2.1–2.5 s for the initial overview build. The native ceiling is
two orders of magnitude better.

## Step 2a — one-time Python → native handoff

Python generates a flat binary file: header, offset table, interned string
blob, and four POD vectors (actions, kinds, sizes, decisions).

| | Result |
|---|---:|
| Python generation of 1M records | 837 ms |
| binary file size | 28.5 MB |
| native `load_binary` total | **86–100 ms** |
| — of which raw I/O | 18 ms |
| — of which parse/copy | 66 ms |

The dataset crosses the boundary once, in ~0.1 s. This is the number that was
missing from the previous experiment; it is negligible next to a compare.

## Step 2b — embedding the native widget in PySide6

`native_qt_bridge` is a nanobind module that builds the four-pane native widget
and returns its `QWidget*`; Python wraps it with `shiboken6.wrapInstance`.

| | Offscreen | X11 `:50` |
|---|---:|---:|
| `load_binary` | 92 ms | 100 ms |
| `create_widget` (4 panes, 1M rows) | 20 ms | 22 ms |
| first paint | 17 ms | 12 ms |
| reset after 1000 decisions | 35 ms | ~950 ms |
| widget wrapped as PySide6 `QWidget` | yes | yes |

`EMBEDDING_OK` in both environments. The distro PySide6 links the system Qt6
libraries, so there is no dual-Qt ABI conflict in one process. This was the
main technical risk and it is resolved.

## Step 3 — decision diff back to Python

Decisions are owned by the native store, keyed by **stable path id** (not row,
because rows move on sort/filter). Every edit appends to an operation log.

| | Result |
|---|---:|
| 1000 decision toggles | ~0 ms |
| `decision_diff()` returning 1000 pairs to Python | 0.1 ms |

Python can pull the compact diff at validation/sync and keep its existing plan
and validation logic. The "receive go/nogo" simplification is achievable.

## Step 4 — recommendation

Proceed with a **real prototype of the hybrid native-view architecture**, not
a full C++ port:

1. Python keeps rsync, parsing, decisions semantics, plan, validation and
   tests. It hands the parsed dataset to native once per comparison.
2. Native owns the four view models, selection, sort, folds and the decision
   table; it handles all interactive operations.
3. At sync, Python pulls the decision diff and builds the plan exactly as it
   does today. The confirmation dialog remains the gate.

Reasons: the measured boundary costs are ~0.1 s in and ~0.0001 s out; the
native view layer is ~100× faster; and the existing Python tests for parsing,
validation and sync remain meaningful.

### Risks to address in the prototype

- **View-level tests** that instantiate a Python `FlatChangeModel` will not
  apply unchanged. They need a Python shim exposing the same API over the
  native store, or a native-side test harness. Core/parser/plan/validation
  tests remain valid.
- **Decision semantics** (inheritance, conflicts, reconciliation) still live
  in Python. The prototype must define exactly when Python pushes decisions
  and when it pulls the diff; keep that contract small.
- **Packaging**: the native bridge is an extra shared object linked against
  Qt6; Debian packaging must build-depend on `qt6-base-dev`.
- **Selection/fold/search behaviour** must be reproduced natively and checked
  against the current app before any switch.
- **Stale results and threading** still need generation counters when a new
  comparison replaces the dataset while the UI is settling.

### What would change the decision

If the prototype's real-tree interaction timings are not dramatically better
than 12–23 s, stop and keep pure Python. The standalone and embedded numbers
leave little doubt, but the prototype is where that claim is actually tested.

## Files in this experiment

- `main.cpp`, `model.hpp` — standalone ceiling app (no Python)
- `bridge.cpp` — nanobind bridge for PySide6 embedding
- `generate_binary.py` — Python producer of the flat binary dataset
- `test_bridge.py` — end-to-end embedding and diff check
- `CMakeLists.txt`, `build.sh` — build
- `README.md` — build instructions, full measurement tables and caveats
