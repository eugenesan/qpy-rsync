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

### Installed location

The extension always lives inside the `qpy_rsync` Python package, so the app
imports it as `qpy_rsync.native_hybrid` from both a checkout and a package:

- source checkout: `src/qpy_rsync/native_hybrid.so`;
- Debian package: `/usr/lib/python3/dist-packages/qpy_rsync/native_hybrid*.so`
  (nanobind adds the Python ABI tag to the filename).

`debian/rules` builds with nanobind (which emits an ABI-tagged filename such as
`native_hybrid.cpython-314-x86_64-linux-gnu.so`) into
`debian/native-hybrid-build/`. `debian/install` copies it from there into the
package staging tree during the normal `dh_install` step, which runs after
pybuild has built the wheel — so the extension reaches the `.deb` without ever
being copied into the source tree. Python imports it as
`qpy_rsync.native_hybrid`; the loader also finds an ABI-tagged sibling by path,
so the app still works if a build uses a different filename.

## Run

Native Qt comparison views are the default on `main`. The setting
**Settings → Advanced → Use legacy Python comparison views** switches to the
original Python renderer for compatibility; it applies immediately. One-off
overrides:

```sh
QPY_PYTHON_VIEW=1 ./qpy-rsync.sh   # force the legacy Python view
QPY_HYBRID_VIEW=1 ./qpy-rsync.sh   # force native (kept for compatibility)
```

If the native extension is missing, the app falls back to the Python view
automatically. The old `advanced/hybrid_view` setting is migrated on startup.

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

## Multi-instance notes

Settings are split between `$XDG_CONFIG_HOME/qpy-rsync/settingsrc` (preferences)
and `$XDG_STATE_HOME/qpy-rsyncstaterc` (transient state). Profile files and the
settings files use PID-based locks; a profile already open in another instance
is loaded as a temporary copy and offered for saving on exit. Logs are named
after the loaded profile, so temporary copies get their own log files.

## Acceptance status

`native-hybrid/bench.py` measures the shipped actions at 520k items (offscreen,
system Python; run with `QPY_HYBRID_VIEW=1 PYTHONPATH=src`):

| action | result |
|---:|---:|
| full `_comparison_finished` | 5.69 s |
| decision toggle / undo | 0.24 s / 0.14 s |
| folder subtree exclude / undo | 0.29 s / 0.14 s |
| sort by size | 0.19 s |
| fold / expand | 0.19 s |
| add 200k unchanged | 1.70 s |
| remove 200k unchanged | 0.77 s |
| destination metadata apply | 0.44 s |

All native view actions meet the "<1 s on 520k items" goal. The remaining
5.69 s end-to-end compare is dominated by Python decision reconciliation and
plan construction, which are outside the native view layer. The documented
acceptance criterion is met for view actions; whether the plan build is in
scope is a product decision.

`tests/unit/test_hybrid_parity.py` is the differential harness for row counts,
exclusion, folding and selection across both views.

## Remaining work before default-on

- real-tree confirmation of the synthetic timings above and a final visual
  pass on the user's tree;
- decide whether the Python plan build counts toward the <1 s goal.
