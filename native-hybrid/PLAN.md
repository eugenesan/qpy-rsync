# Hybrid view: remaining work toward parity

## Current state

- Three native table panes and one native overview tree, embedded in
  `MainWindow` through `shiboken6.wrapInstance`.
- Python owns rsync, parsing, plan, validation, decisions semantics and tests;
  the Python model keeps changes/directories/decisions but skips row/filter
  and directory rebuilds while native is active.
- Working: decision checkbox, toolbar action filters, show-excluded, search
  (including the `dir/` variant), sort, folds, shared selection, undo/redo,
  metadata merge, unchanged-item transitions, scroll preservation.
- Measured at 520k: compare 0.9 s, undo 0.11 s, decision ~0.1 s, metadata
  merge 0.1 s.

## 1. Overview pane — DONE

The native side now exposes separate `create_tables_widget()` and
`create_overview_widget()` factories. `MainWindow` places the native overview
in the existing `log_splitter` slot through `NativeOverviewShim`, which
provides the signals and small API the rest of the window expects. Verified
offscreen: 30,000 overview folders, 100,000 table rows, compare 0.91 s.

Original plan for reference:

```
create_tables_widget() -> QWidget*
create_overview_widget() -> QWidget*
```

Each returns a separate native `QWidget`. Python can wrap both and put them in
different places in its own layout: tables in the comparison splitter slot,
overview in the current `OverviewPane` slot. The C++ side keeps both views
over the same `DataStore`, so there is no second data copy.

Work needed:

1. Split `create_widget()` in `bridge.cpp` into the two factories.
2. Add a native overview widget with a small statistics strip (selected
   count/size, matching `StatisticsBar`) above the tree.
3. Add a Python wrapper `NativeOverviewView` exposing the methods MainWindow
   calls on `OverviewPane`: `set_paths`, `set_aggregates`, `set_statistics`,
   `folder_activated` signal.
4. In `_enable_hybrid_view`, replace the Python `OverviewPane` in its layout
   slot and route those calls; keep the Python pane hidden but alive so the
   rest of the app keeps working.
5. Preserve the Python overview's depth indicators, share bars and context
   menu — those are currently missing and are the "bare" appearance reported.

This is a contained change to the bridge and the two wrappers; no changes to
data ownership.

## 2. Table panes matching the Python view — DONE (first pass)

Native delegates now paint action colours, alternating stripes, excluded
dimming, folder chevrons/indentation; the Action pane has a fixed width and
native context menus reach the existing external-tool and diff actions.
Icons and exact status colours still need a visual comparison pass.

Original scope for reference:

- action colour per row (the palette is defined in Python:
  `gui/action_colours.py`);
- icons for actions, file types and folders;
- alternating stripes and excluded dimming;
- path elision with chevrons for the directory hierarchy;
- the fixed-width Action pane and stretchable Source/Destination panes.

Approach: a native `QStyledItemDelegate` per pane. Pass the colour palette and
icon file paths once through the bridge at setup time (a handful of values,
not per row). Derive excluded/dimmed state from the native decision table
already owned by C++. Keep the delegate work in C++ so painting stays native.

Selection parity: expose `selected_path()` (already done) and connect it to
the existing external-tool and confirmation-dialog code paths in MainWindow;
currently the value is reported to Python but unused.

## 3. Search and filters

- Jump search including the `dir/` variant is working (fixed by deriving
  `is_dir` from the change kind and implementing directory-only exact match
  plus ancestor closure).
- A persistent "Filter list" mode is not planned; the Python app never had
  one in the shipped build.

## 4. Remaining risks

- Qt delegate code is the part most likely to differ visually from PySide6;
  compare screenshots after each step.
- The native overview must emit folder-activation back to Python so clicking
  a folder still selects it in the tables.
- Packaging still needs `qt6-base-dev` as a build dependency.
- Keep the flag off by default until the two views are visually comparable.

## Suggested order

1. Overview split + statistics strip (biggest visible gap).
2. Delegate/colour/icon work for the three tables.
3. Selection → external tools and confirmation dialog.
4. Packaging and a final differential screenshot pass against pure Python.
