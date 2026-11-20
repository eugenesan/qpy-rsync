# Performance analysis: bottlenecks, causes, and attempted solutions

This document consolidates what we learned about qpy-rsync performance on a
large tree (about 1.2M objects, of which ~526k are changes). It covers the
native-extension experiment and the pure-Python tuning that followed it.

Measurements come from the `timing*.txt` files under the repository root and
from repeatable synthetic harnesses in `native/` on the experiment branch.
Timings vary with cache state and endpoint load; the numbers below are ranges
and each conclusion was checked against at least two runs where possible.

## 1. Where the time goes in a full compare

| Phase | Typical range | Notes |
|---|---:|---|
| rsync dry run | 16–26 s | I/O bound; cannot be accelerated from Python |
| parse (Python) | 3.2–3.6 s | ~1.5 s of it is record parsing and object creation |
| journal writes | 0.15 s now, 1.4–1.7 s before | raw-output logging is now opt-in |
| view/model rebuild | 17–21 s | dominated by Qt, see below |
| destination metadata rsync | 13–16 s | one `--list-only` run, off the GUI thread |
| inventory rsync (both trees) | ~31 s total | destination 13–16 s, source 13–26 s |
| matching (555k paths) | 2–3.5 s | Python set intersection |

End-to-end, "Comparison ready" was ~20–29 s in pure Python after the tuning
changes. The rsync dry run itself remains the single largest cost and is not
addressable in application code.

## 2. Bottlenecks and their causes

### 2.1 `view.set_changes` — 12–23 s

The largest non-rsync cost. A structural change (new comparison, showing
unchanged items, hiding them) calls `set_changes`, which:

- resets a `QAbstractTableModel` with 550k–964k rows;
- three visible tree views invalidate their row mappings and repaint;
- emits `changes_updated`, which rebuilds the overview (2 s) and the plan
  (3–4 s) in the same signal cascade.

In isolation, with no views attached, the same `set_changes` costs ~4.4 s.
The extra 8–18 s is Qt view work. This is why synthetic benchmarks repeatedly
looked better than the real application.

### 2.2 `ui.plan_rebuild` — 3.6–4.6 s

`build_execution_plan` makes one pass over 520k changes and creates 520k
`PlanItem` objects, then a separate digest loop. `_rebuild_plan_summary` then
makes three more full passes: a sorted `(path, index)` list, an items-by-path
dict and a changes-by-path dict.

### 2.3 `ui.overview_update` — 2.1–2.5 s initial

`OverviewModel` is already a `QAbstractItemModel`, but it eagerly creates
30k `OverviewNode` objects, sorts every node, and refreshes visible children
and level totals for all of them. Incremental filter updates are cheaper
(~120 ms), so the cost is concentrated on the initial build.

### 2.4 Filter and decision paths

| Operation | Cost | Cause |
|---|---:|---|
| global filter refresh | 0.5–1.8 s | full flag/row/aggregate pass in Python |
| show/hide excluded | ~1.8 s | rebuild of the filtered row set |
| decision refresh | ~190–250 ms | incremental patch; already near the floor |
| undo of a global decision | 2–3× a single edit | many changed paths force a full filter pass |

### 2.5 rsync inventory I/O

Destination metadata and unchanged detection need `--list-only` listings.
Two listings (destination for metadata, source for unchanged) are required
because rsync's compare output does not report unchanged objects, and because
a single multi-source `--list-only` invocation deduplicates identical relative
names — precisely the unchanged items whose metadata we need.

### 2.6 Logging

Before the opt-in change, every itemized record was written with a timestamp
and a flush: ~1.4–1.7 s of Python work and hundreds of MB per run. Raw output
is now off by default and still batched when enabled.

## 3. Attempted solutions and outcomes

### Kept — repeatable benefit

| Change | Result |
|---|---|
| Raw rsync output logging opt-in | Removes the ~1.5 s write phase and the 800 MB logs; application events/timings still logged |
| Single-pass destination listing | One rsync instead of filtered + fallback; `QPY_DEST_METADATA_TWO_PASS` in Advanced restores the old path |
| In-place destination metadata merge | 1158 ms → 394 ms (2.94×) at 520k changes / 100k entries |
| Cache full destination listing for inventory | Inventory lists source only; no duplicate destination rsync |
| Skip redundant `set_changes` before inventory | Removes a 13–15 s freeze before progress messages start |
| Inventory toggle is config-only | ~8 ms on disable; no view rebuild or overview redraw |
| Journal logs every rsync command | No longer ambiguous which rsync runs are in flight |
| End-to-end timing probes | Made the Qt-side gaps visible; enabled the analysis in this document |

### Tried and rejected — no repeatable benefit

| Experiment | Finding |
|---|---|
| Native single-pass plan indexes + fingerprint in loop | Plan indexes 0.33 s → 0.29 s in isolation; no clear gain in real runs |
| Lazy overview node preparation | Deferred ~86 ms of a ~160 ms synthetic build; no clear gain in real runs |
| Both were reverted together in commit `57f6381` |

### Parked — correct but not a net win

The `native-extension-experiment` branch implements all eight planned
workstreams behind `QPY_RSYNC_NATIVE=0|1|auto`, with differential harnesses
for parser, filter and plan. Raw kernels are much faster:

| Kernel | Python | Native |
|---|---:|---:|
| filter pass | ~620 ms | 10–150 ms |
| plan build | 1,386 ms | 466 ms |
| glob search | 207 ms | 42 ms |
| parse | 1,566 ms | ~500–900 ms |

But application-level timings did not improve: view built 20–21 s versus 17 s
in Python, and the costs moved rather than disappeared. The causes were:

1. `nanobind` `def_ro` vectors copy on each property access; reading them in
   per-item loops turned a 40 ms patch into 1.2 s twice before it was caught.
2. A lazy `Change` sequence made Python loops ~25× slower than list indexing
   (`__getitem__` + dict cache); materialising once fixed it.
3. The Qt view layer, not the kernels, dominates. Native kernels cannot fix it.

Conclusion: a native *extension* cannot remove the bottleneck. A full C++
Qt port that owns the model and views would be required, and is a separate
project.

### Considered but not implemented

| Idea | Why not |
|---|---|
| Incremental append of unchanged rows + deferred plan rebuild | Rejected as "sweeping the issue under the rug": it would smear the same work over the timeline without reducing it |
| Repainting suppression (`setUpdatesEnabled`) during `set_changes` | Would compress paint events but not reduce the model reset/index invalidation that dominates; never measured |
| One-process combined listing via `--files-from /` | Works only when both endpoints are on one host; our two-operand `--list-only` form deduplicates common names and loses destination metadata |
| Always preloading the source listing | A/B measured 26 s concurrent vs 13 s standalone source listing: time-to-unchanged was unchanged while every compare paid more. Kept as an opt-in Advanced setting, off by default |

## 4. Current conclusion

The remaining hard problems are all in the Qt view layer:

1. `view.set_changes` (12–23 s) — full model reset and repaint of three views
   with half a million to a million rows.
2. `ui.plan_rebuild` (3.6–4.6 s) — several full passes over 520k objects.
3. `ui.overview_update` (2.1–2.5 s) — eager construction of 30k tree nodes.

All three are structural: they need a different data flow or a model/view
rewrite, not micro-optimisation. The pure-Python branch is in a good handover
state with the lower-risk improvements kept and the speculative ones reverted.
