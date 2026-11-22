# Hybrid app: native Qt view layer

Branch: `hybrid-app`. This is the integrated native-view architecture recommended
in `native-qt-model/CONCLUSION.md`. Python remains the default; the native path
is opt-in and fully reversible.

## Status

**Feature-complete for the comparison view.** Python keeps rsync, parsing,
decision semantics, plan, validation, sync and the tests. Native Qt owns the
four view models (three tables plus the overview), the volatile decision table
and the decision diff.

Working and verified:

- one Python → native handoff per comparison, with incremental append/truncate
  for unchanged-item transitions;
- decision checkbox (mouse and Space), action filters, show-excluded, search
  including the `dir/` variant, column sorting, folder folding, shared cursors,
  undo/redo, destination metadata, stable cursor/scroll across exclude and undo;
- full column/row/header context menus, item tooltips, keyboard shortcuts and
  the overview share bars / stats footer / jump-to-folder;
- Python pulls the compact `(path_id, decision)` diff when it needs it;
- the setting toggles live in both directions, and a missing or incompatible
  `.so` falls back to the Python view without user-visible failure.

### Test status

Both configurations are green:

```sh
./qpy-rsync-test.sh -q                 # 425 passed, Python view
QPY_HYBRID_VIEW=1 ./qpy-rsync-test.sh -q   # 425 passed, native view
```

## Build

```sh
./native-hybrid/build.sh
```

Requires `qt6-base-dev`, Ninja and nanobind. The module is copied to
`src/qpy_rsync/native_hybrid.so` (gitignored). Debian builds it from source:
`Architecture: any`, with `cmake`, `ninja-build`, `qt6-base-dev`, `python3-dev`
and `python3-nanobind` as build dependencies.

## Run

Enable **Settings → Advanced → Use native Qt comparison views (experimental)** —
it applies immediately, including turning the native views off again — or use
`QPY_HYBRID_VIEW=1` for a one-off run:

```sh
QPY_HYBRID_VIEW=1 ./qpy-rsync.sh
```

With the setting/flag off nothing changes: the Python view is the shipped
default.

## Decision contract

The native store owns the volatile decision table keyed by **stable path id**.
Python owns decision *semantics* (inheritance, conflicts, reconciliation).

- **Python → native (push)**: once per comparison through `set_changes()`;
  after undo/redo through `apply_python_decisions()`; after a new comparison or
  an inventory/metadata result through `set_changes()`/`set_destination_metadata()`.
- **Native → Python (pull/notify)**: every user edit calls the decision callback
  with `(path_id, decision)`. `_on_native_decision` mirrors it into
  `ChangeDecisions`, including whole-subtree decisions for synthesized folder
  ids, then marks the plan stale through the existing Python path.
- Folders synthesized by native have ids beyond the change list. They are
  resolved by `path_of_id()` and mirrored onto every change below that prefix.
- The compact `decision_log` remains available through `decision_diff()` for
  validation/sync, but the shipped code keeps using the Python plan as the gate.

## Measured on this slice

| | Result |
|---:|---:|
| Python → native handoff of 1M changes | 0.70 s |
| removing 200k unchanged at 300k changes | 0.52 s (was 1.95 s) |
| destination metadata apply, 300k items / 30k folders | 0.40 s |
| decision toggle / estimated summary, 300k + 100 decisions | ~0.17 s / 0.62 s |
| decision diff, 1000 entries into Python | 0.1 ms |
| native comparison view work at 520k | ~0.9 s |

The handoff uses an in-process vector API, so it is the real integration cost.

## Remaining work before default-on

- real-tree differential timing against the "<1 s per compare-view action on
  520k items" acceptance criterion, including the Python plan rebuild;
- a systematic differential harness for decisions, folds, selection, overview
  totals and scroll restoration (currently covered by unit tests plus manual
  screenshot comparisons);
- final visual pass on the user's tree.

## Not applicable

- persistent filter mode — never existed in the shipped Python view;
- full C++ port — explicitly rejected in `docs/cpp-qt-conversion-analysis.md`.
