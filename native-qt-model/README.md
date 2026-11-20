# Native Qt model experiment (phase 1: ceiling measurement)

This is a **standalone C++ Qt application**. It contains no Python, no rsync
and no application logic. Its only purpose is to measure what native Qt models
can do with the shape of data our comparison view produces: one shared dataset,
three views, a million-plus rows.

Branch: `native-qt-model-experiment`.

## What it builds

- `DataStore`: flat vectors of paths (strings), action/kind/size/decision codes
  and a `visible` row-index vector. Decisions are keyed by **path id**, never by
  row, because rows move after sorting or filtering. Every decision change is
  appended to an operation log; `decision_log` is the compact diff Python could
  request at validation/sync time.
- One `QAbstractTableModel` per pane over the shared store. Each model maps the
  same records to that pane's columns, so there is no data duplication.
- Three `QTableView`s with uniform row heights, laid out side by side.

## Build and run

Requires `qt6-base-dev` and Ninja (installed on the host for this experiment).

```sh
./native-qt-model/build.sh
QT_QPA_PLATFORM=offscreen /tmp/opencode/qpy-qt-model-build/native_qt_model --items=1000000
```

`--items=N` sets the dataset size (default 1,000,000).

## Measured results

Host: Qt 6.10.2, GCC 15.2, Release build, offscreen platform.

| Operation | 1M rows | 1.5M rows |
|---|---:|---:|
| store.generate | 149 ms | 233 ms |
| models.create | 0 ms | 0 ms |
| first paint, 3 views, two `processEvents()` | 17 ms | 17 ms |
| sort by size + reset + paint | 56 ms | 80 ms |
| filter (show excluded) + reset + paint | 11 ms | 12 ms |
| 1000 decision toggles | 0 ms | 0 ms |
| repaint after decision batch | 9 ms | 8 ms |
| diff snapshot (1000 entries) | 0 ms | 0 ms |
| full reset with a new dataset | 156 ms | 229 ms |
| resident memory | 131 MB | 178 MB |

For comparison, the current Python implementation takes **12–23 s** for
`view.set_changes` at 520k rows, and that climbs with row count. The native
upper bound is two to three orders of magnitude faster.

## Caveats — read before drawing conclusions

1. **Offscreen does not paint pixels.** `processEvents()` performs layout and
   model calls but not real rasterisation. An X11 run will be slower for first
   paint. The numbers measure model/layout overhead, not GPU/xrender cost.
2. **No delegates.** The real application draws icons, colours, stripes,
   chevrons and elided paths. Those are C++ in the real app too, but they are
   not simulated here.
3. **No Python boundary yet.** Data is generated natively. The cost of the
   one-time handoff from Python is the central question of phase 2.
4. **No real rsync.** Record variety is simplified. The shape (1M rows, three
   views, volatile decisions) is what matters.
5. **Decisions are simple.** Inheritance and conflict detection are not
   simulated; only the storage and diff mechanics are.

## Interpretation

If these numbers survive a real X11 run and a one-time Python handoff, the
bottleneck we measured in `docs/performance-analysis.md` is confirmed to be the
Python model/view adapter, not Qt. The next experiment should:

1. run the same binary on X11 to get a true first-paint number;
2. add a one-time bulk transfer from Python (flat vectors + interned path
   strings) and measure it;
3. add a compact return path for the decision diff and validate that Python's
   existing plan/validation tests still work against it.

Do not start a full C++ port until step 2 is measured.
