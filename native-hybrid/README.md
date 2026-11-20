# Hybrid app: native Qt view layer (working slice)

Branch: `hybrid-app`. This is the first integrated slice of the architecture
recommended in `native-qt-model/CONCLUSION.md`.

## Status

**Working, opt-in, display-and-decision slice.** It is not yet full feature
parity with `FlatComparisonView`; see "Not yet wired" below.

- Python keeps rsync, parsing, decisions semantics, plan, validation and sync.
  In hybrid mode its model keeps the change list, directories and decisions for
  the plan, but skips the expensive row/filter rebuild.
- Native Qt owns the four view models (three tables plus the overview tree),
  the volatile decision table and the decision diff.
- The dataset crosses Python → native exactly once per comparison. The native
  panes use real columns: Source (name/size/modified), Action (action/decision
  checkbox/reason), Destination (path/size/modified), plus the overview tree.
- A checkbox in the native Action pane edits a decision; the change is
  mirrored into `ChangeDecisions` and the plan is marked stale through the
  existing Python path.
- Selection is shared across the three native panes and reported to Python.
- The existing action-filter checkbox, path filter/search box, sort and
  directory folds are routed to the native models when hybrid mode is active.
  Decision toggles take ~19 ms: only the checkbox row is repainted unless the
  decision actually hides rows. Show-excluded, undo/redo and unchanged-item
  transitions are routed to the native store as well.
- Python pulls the compact `(path_id, decision)` diff whenever it needs it.

## Build

```sh
./native-hybrid/build.sh
```

Requires `qt6-base-dev`, Ninja and nanobind. The module is copied to
`src/qpy_rsync/native_hybrid.so` (gitignored).

## Run

Enable **Settings → Advanced → Use native Qt comparison views (experimental)**,
or use `QPY_HYBRID_VIEW=1` for a one-off run:

```sh
QPY_HYBRID_VIEW=1 ./qpy-rsync.sh
```

With the setting/flag off nothing changes: the Python view is the default and
all 417 tests pass. A minimal smoke test is available:

```sh
PYTHONPATH=src /usr/bin/python3 native-hybrid/test_hybrid.py
```

## Measured on this slice

| | Result |
|---|---:|
| Python → native handoff of 1M changes | 0.70 s |
| native `row_count` | 1,000,000 |
| native decision diff, 1000 entries pulled into Python | 0.1 ms |
| startup with hybrid view on X11 `:50` | ok |

The handoff is the in-process vector API (no binary file), so it is the real
integration cost.

## API

`qpy_rsync.gui.native_hybrid_view.NativeHybridView`:

- `set_changes(changes)` — one-time handoff, then `refresh()`
- `widget` — the native `QWidget`, wrapped with `shiboken6.wrapInstance`
- `on_decision_changed(callback)` — native → Python decision edits
- `set_checkstate(row, checked)` — test hook that exercises the checkbox path
- `decision_diff()` — compact change log for validation/sync
- `shutdown()` — drop the Python callback before interpreter shutdown

## Not yet wired

This is a vertical slice, not a completed migration. Still using the Python
view or missing from the native side:

- selection is shared natively and reported to Python, but not yet wired to
  external tools or the sync confirmation's path display;
- search is jump-only (no persistent filter mode);
- scroll position is not preserved across a full model reset;
- the Python model's `rowCount()` is 0 in hybrid mode; code that still reads it
  must be routed to the native view.
- sync confirmation and validation still read the Python plan;
- packaging (Debian build-dependency on `qt6-base-dev`);
- command-line and Advanced-setting toggle both work; enable requires a new
  comparison or restart to take effect.

Do not switch this on for production use. The purpose is to validate that the
boundary, embedding and decision round-trip work in the real application
before investing in full feature parity.

## Next steps

1. Wire native selection/fold/search so the hybrid view is usable interactively.
2. Skips the Python view's `set_changes` work when hybrid is active, so the
   measured gains can be realised rather than paid twice.
3. Add the Advanced-setting toggle and packaging.
4. Re-measure against `docs/performance-analysis.md` and decide whether to
   complete the migration.
