# Hybrid view: plan and status

## Current state

- Three native table panes and one native overview tree, embedded in
  `MainWindow` through `shiboken6.wrapInstance`.
- Python owns rsync, parsing, plan, validation, decision semantics, sync and
  the tests. Its model keeps changes/directories/decisions but skips row/filter
  and directory rebuilds while native is active.
- Native owns the view models, the volatile decision table, folds, sort,
  selection and the compact decision diff.
- The dataset crosses Python → native once per comparison; unchanged-item
  transitions append/truncate incrementally.
- Both test configurations are green (425 passed with the flag off and on), the
  setting toggles live, and a missing native module falls back to Python.

## 1. Overview pane — DONE

`create_tables_widget()` and `create_overview_widget()` are separate factories.
`MainWindow` places the native overview in the existing `log_splitter` slot
through `NativeOverviewShim`. The overview has Item / Share / Items / Size
columns, painted share bars, a Total row, correct aggregates and a stats footer
with the same icon set as the toolbar. Double-clicking a folder selects it in
the three lists.

## 2. Table panes matching the Python view — DONE

Wide Item column, narrow Items and human-readable Size, a virtual root plus
synthesized folder rows with aggregates, runtime-generated action icons (shared
with the Python toolbar and stats), folder/file icons, chevrons, directory
rules, all-row stripes, action colours, dimmed exclusions, a fixed-width
Decisions pane and stretchable Source/Destination panes.

## 3. Parity follow-up — DONE

Palette-based striping for dark themes, no trailing blank space in any view,
chevron folding, synchronized cursors, full row and header context menus, item
tooltips, all Python list keyboard shortcuts, overview jump, and stable cursor
and viewport across exclude/undo. Show-unchanged no longer flips the persistent
inventory button on.

## 4. Search and filters — DONE

Jump search including the `dir/` variant. No persistent filter mode: the Python
app never had one in the shipped build.

## 5. Interaction correctness — DONE

- stable path ids for decisions, keyed independently of row position;
- whole-subtree decisions for folders, mirrored into the Python decision store;
- generation guard so a stale compare result cannot overwrite a newer dataset;
- 60 s watchdog for a hanging destination-metadata listing;
- completion is announced only after destination metadata resolves.

## 6. Packaging and rollout — DONE

Debian builds the extension from source (`Architecture: any`, build deps for
CMake/Ninja/Qt6/nanobind). The Python view stays the default; the native view is
an opt-in Advanced setting or `QPY_HYBRID_VIEW=1`, toggleable at runtime.

## 7. Remaining work before default-on

- Real-tree differential timing against the "<1 s per compare-view action on
  520k items" acceptance criterion; decide whether the Python plan rebuild is
  in scope.
- A systematic differential harness for decisions, folds, selection, overview
  totals and scroll restoration, complementing the unit tests and manual
  screenshot comparisons.
- Final visual/behavioural pass on the user's tree.

## Risks and mitigations

- Qt delegate code is the most likely visual divergence: compare screenshots
  after any delegate change. The icons and colours are now shared with Python,
  which removed the largest source of drift.
- The Python model's `rowCount()` is answered from the native row map in hybrid
  mode; legacy code that reads other view-level state must be routed the same
  way. Both test configurations enforce this.
- Native model manipulation must stay on the GUI thread; metadata and inventory
  results are delivered through Qt signals on that thread.
