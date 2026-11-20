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
- A fourth pane: a native `QTreeView` with an `OverviewModel` (`QAbstractItemModel`)
  built from the same paths, with 30k folder nodes and per-folder totals.

## Build and run

Requires `qt6-base-dev` and Ninja (installed on the host for this experiment).

```sh
./native-qt-model/build.sh
QT_QPA_PLATFORM=offscreen /tmp/opencode/qpy-qt-model-build/native_qt_model --items=1000000
DISPLAY=:50 /tmp/opencode/qpy-qt-model-build/native_qt_model --items=1000000
```

`--items=N` sets the dataset size (default 1,000,000).

## Measured results

Host: Qt 6.10.2, GCC 15.2, Release build, offscreen platform.

| Operation | offscreen 1M | offscreen 1.5M | X11 (:50), 1M and 1.5M |
|---|---:|---:|---:|
| store.generate | 130 ms | 233 ms | 137–208 ms |
| models.create | 0 ms | 0 ms | 0 ms |
| overview.build (30k folders) | 25 ms | 36 ms | 25–36 ms |
| first paint, 4 panes | 17 ms | 17 ms | 14–17 ms |
| 10 × scroll to row 100k+ | — | — | 429–972 ms |
| sort by size + reset + paint | 50 ms | 80 ms | 57–886 ms |
| filter + reset + paint | 11 ms | 12 ms | 53–119 ms |
| 1000 decision toggles | 0 ms | 0 ms | 0 ms |
| repaint after decision batch | 9 ms | 8 ms | 22–47 ms |
| diff snapshot (1000 entries) | 0 ms | 0 ms | 0 ms |
| full reset with a new dataset | 140 ms | 229 ms | 141–208 ms |
| resident memory | 134 MB | 178 MB | 137–185 MB |

Paint-related timings on X11 vary by an order of magnitude between runs
depending on desktop load; the ranges are the honest result. Structural work
(generate, overview build, reset) is stable. Even the worst paint figure is
two orders of magnitude below the Python implementation.

For comparison, the current Python implementation takes **12–23 s** for
`view.set_changes` at 520k rows, and that climbs with row count. The native
upper bound is two to three orders of magnitude faster.

## Caveats — read before drawing conclusions

1. **X11 column is the realistic one.** Offscreen performs layout and model
   calls but no rasterisation. On X11, sorting with real repaint costs 886 ms
   rather than 50 ms; first paint stays ~16 ms because only the visible rows
   are painted. Even the X11 figures are two orders of magnitude below the
   Python implementation.
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
