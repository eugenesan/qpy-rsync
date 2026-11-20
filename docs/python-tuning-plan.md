# Where the native experiment left us, and the Python tuning plan

## Conclusion of the hybrid-extension experiment

The single-module native extension (`_qpy_native`) is correct and well tested:
every kernel has a byte-for-byte differential harness against the Python
implementation, and the full suite passes with the flag on and off.

It is not, however, a net win in the running application.

Measured on a 520,000-item tree:

| Kernel (pure computation) | Python | Native |
|---|---:|---:|
| filter pass | ~620 ms | ~10–150 ms |
| plan build | 1,386 ms | 466 ms |
| glob search | 207 ms | 42 ms |
| rsync parse | 1,566 ms | ~500–900 ms |

But the application-level numbers moved the other way:

| Application phase | Python run | Native run |
|---|---:|---:|
| Compare parse | 3.53 s | ~1.3 s |
| Comparison view built | 17.18 s | 20.7–21.4 s |
| Comparison ready | 25.89 s | 23.4–29.1 s |
| one exclusion | 163 ms | 159 ms (after fixing a boundary bug) |
| show/hide excluded | ~1.8 s | ~1.8 s |

The reason is the boundary and the Qt layer, not the kernels:

1. `nanobind` `def_ro` vectors copy on every property access. Reading them
   inside per-item loops turned a 40 ms decision patch into a 1.2 s one twice
   before it was caught.
2. Materialising 520k `Change` objects lazily made Python loops ~25x slower
   than a plain list (`__getitem__` + dict cache versus list indexing).
3. `view.set_changes` costs 15–24 s in the real app: a full model reset and
   repaint of 550k–964k rows across three visible tree views, plus a 3.6–4.6 s
   plan rebuild in the same signal cascade. No native kernel touches this.

So a native **extension** cannot fix the dominant cost. Only two things can:
further Python/Qt tuning, or a full C++ Qt port that removes the boundary and
owns the model and views.

## Branch state

- `native-extension-experiment` keeps the complete experiment: all eight
  stages, differential harnesses, benchmarks, timing gates and CI workflow.
  Python remains the default; `QPY_RSYNC_NATIVE=0|1|auto` selects the backend.
- `python-tuning` is branched from `main` and contains only changes that help
  the shipped Python build:
  - in-place metadata merge (affected changes only);
  - one-pass destination listing (`QPY_DEST_METADATA_TWO_PASS=1` restores the
    old two-run behaviour for measurement);
  - raw rsync output logging is opt-in in Advanced settings;
  - the exit-time profile prompt explains the changed field and saves to the
    known profile file;
  - end-to-end `view.*` timing probes.

Nothing in `python-tuning` depends on the extension.

## Python tuning targets, ranked by measured cost

From `timing28.txt` / `timing30.txt` (520k changes):

| Target | Measured | Idea |
|---|---:|---|
| `view.set_changes` repaint | 15–24 s | Avoid full rebuilds; reuse row objects, reset once for three views, and stop re-emitting redundant `changes_updated` cascades. |
| `ui.overview_update` (initial) | 2.1–2.5 s | Build the 30k-node tree incrementally or lazily; avoid setting every aggregate at once. |
| `ui.plan_rebuild` | 3.6–4.6 s | Build the sorted path index and item map in one pass; avoid materialising 520k `PlanItem`s twice. |
| show/hide excluded | ~1.8 s | Reuse `_rebuild_visible_rows` with a cached excluded set. |
| `model.filter_refresh` | 0.5–1.8 s | Keep the flat-flag arrays; avoid re-deriving them from objects. |
| decision refresh | ~190 ms | Already close to the floor; leave alone. |

The overall goal stays the original one: every compare-view action under ~1 s
on 520k items. The `view.set_changes` path is the only remaining blocker.

## Prerequisites for a future C++ Qt port

- Keep the differential harnesses as the behavioural oracle; they already
  encode filter, parse and plan semantics.
- Decide up front whether the model and all three views move to C++ at once.
  A partial port recreates exactly the marshalling problem seen here.
- Preserve the Python implementation behind a build flag for at least two
  releases, and use the same `QPY_RSYNC_*` gates for rollout.
- Budget from the measured costs, not from raw kernel speed: the Qt view layer,
  not the parser or filter, is the expensive half of the application.
