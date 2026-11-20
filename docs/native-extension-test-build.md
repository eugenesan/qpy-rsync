# Native extension experiment — test build notes

**Branch:** `native-extension-experiment` (forked from `main` at `36d922a`).
This is an experiment, not a product decision. See `cpp-extension-analysis.md`
for the research behind it.

## What the test build contains

- `native/native_module.cpp` — one nanobind module exposing `NativeFilter`.
  It owns persistent flat arrays (change index, directory index, is-dir,
  sizes) and computes visible rows, visible change indices and per-directory
  aggregates from boolean flags passed by Python.
- `native/CMakeLists.txt`, `native/build.sh` — CMake + nanobind build; copies
  the resulting shared object into `src/qpy_rsync/_qpy_native.so`.
- `native/bench_native.py` — synthetic 520k-item benchmark comparing the
  Python filter pass with the native kernel.

Build:

```bash
/usr/bin/python3 -m pip install --user --break-system-packages nanobind
./native/build.sh
PYTHONPATH=src /usr/bin/python3 native/bench_native.py
```

## One module or several?

**One extension module, many classes/functions.** A single `_qpy_native`
shared object can hold the visibility kernel, the plan kernel, the filter-file
generator and a search index as separate native classes. Splitting into
several modules would multiply ABI/build/packaging work and encourage
per-call object marshalling — the exact mistake the research warns about.
The only reason for a second module would be an independently licensed or
independently built dependency, which does not apply here.

## Measured result (synthetic, 550,590 rows)

| Step | Time |
|---|---:|
| Python `set_changes` (includes model build) | 4,409 ms |
| Python `_apply_filters` | 619–643 ms |
| Native one-time array load | **11 ms** |
| Native `apply` | **39–56 ms** |

The native kernel currently receives flags that the Python filter pass still
has to compute, so it is **not a drop-in replacement yet** — the ~16× speedup
is for the row/aggregate part only. The next step is to move the
change-visibility and directory-flag passes into the same native object so
the whole filter path runs without rebuilding Python arrays.

## Compare parsing (added after merging `main`)

The same module now also exposes `parse_records()`, an experimental native
rsync itemized-record parser. Benchmark on a synthetic 43.9 MB stream of
520,000 records:

| Step | Time |
|---|---:|
| Python `parse_record` loop | 1.66 s |
| Native `parse_records` (full arrays returned) | **0.25 s** |
| Native array conversion to Python lists | 0.01 s |

`native/check_parse.py` verifies six tricky records (create, update, directory,
two deletions, symlink) against the Python parser. In the real application the
3.5 s parse phase also includes per-line callback and journal work, so the
native kernel would save roughly 1–2 s there unless `Change` object creation is
also eliminated.

## Persistent comparison backend (Stage 1–2a)

`_qpy_native.NativeComparison` owns the row arrays for one comparison. A build
call (`set_changes`) passes the layout once; each filter pass then takes only
small scalar flags and returns row positions. `native/check_model.py` compares
its output to `FlatChangeModel` byte-for-byte on ten scenarios (nine after the
first commit, seven of them now driven by the native flag kernel).

`native/bench_filter.py` on 520,000 changes / 550,590 rows / 30,590 folders:

| Filter | Python `_apply_filters` | Native `filter()` | Speedup |
|---|---:|---:|---:|
| all | 620 ms | 10.1 ms | 61x |
| updates only | 328 ms | 7.3 ms | 45x |
| creates only | 602 ms | 10.3 ms | 58x |

The full 520,000-item differential passes. Path-pattern matching is still
Python-side and is planned for the search stage of the backend plan.

## Model integration (Stage 3)

`FlatChangeModel` now accepts `QPY_RSYNC_NATIVE=0|1|auto`. Unset and `0` keep
the pure-Python path; `1` uses the extension when present; `auto` uses it when
present. The full suite (411 tests) passes in all three modes, and
`tests/unit/test_native_backend.py` checks that both paths produce identical
visible rows, aggregates, overview and subtree totals.

On the 520,000-change tree, an action-filter pass costs 326 ms in Python and
150 ms through the native backend. `set_changes` is slightly slower with the
native mirror (4.75 s vs 4.24 s) because it still builds the Python `Change`
list and then copies it into native arrays; Stage 4 removes the duplicate
work by parsing into native storage directly.

## Compare parser integration (Stage 4)

`CompareService` can now accumulate rsync records directly into native flat
arrays and expose them as a lazy `Sequence[Change]`. `native/check_parse.py`
validates every field of eleven record types plus malformed-input errors
against the Python parser. The full suite passes with the flag both off and on
(412 tests), including a `CompareService` parser-parity test.

The parse phase is faster (about 1 s saved on 520,000 records) because Change
objects are created when the GUI consumes them, not while rsync streams. This
does not yet reduce the total time to the populated view; that needs the model
to consume native arrays directly (Stage 4b).

## Execution plan kernel (Stage 5)

`build_execution_plan` can now run its item loop natively. The extension emits
compact item arrays, summary counters and the exact byte stream that Python
hashes for `items_fingerprint`; `PlanItem` objects are created lazily and
cached. `native/check_plan.py` verifies items, summary and fingerprint against
the Python implementation in four decision scenarios.

On 520,000 changes: **1,386 ms → 466 ms** (3x), identical fingerprint. All 413
tests pass with the flag on and off.

## Search and filter-list mode (Stage 6)

The extension now implements the same path-pattern semantics as the Python
model (substring, `*` / `?` / `[...]` globs, slash paths, trailing-slash
directory patterns) in a `filter_pattern()` kernel, plus a `search_rows()`
index. `native/check_model.py` validates six pattern scenarios byte-for-byte.

The **Filter list** toggle is back in the comparison controls, but only shown
when the native backend is active; the Python path keeps search jump-only.
On 520,000 rows a glob search drops from 207 ms to 42 ms. All 415 tests pass
in both modes.

## GIL and generation safety (Stage 7)

All native kernels that only touch flat arrays now release the GIL for their
computation. On the Python side, filter results are copied into a
`_NativeSnapshot` with a generation number and published through
`_publish_native_snapshot`, which ignores snapshots older than the latest
published one. A regression test covers stale-result rejection. All 416 tests
pass with the flag on and off.

A worker thread is not yet used; kernels are fast enough that the GUI thread
still meets the <1 s target. The snapshot boundary is worker-ready.

## Fixed: post-compare hang at large sizes

The first end-to-end run with the native backend froze between "comparison
complete" and the first UI update. A `faulthandler` stack showed the O(n^2) in
`_LazyPlanItems._item_at`: nanobind's `def_ro` vectors are copied on every
property access, and the main window iterates `plan.items` several times. The
arrays are now snapshotted once in `_LazyPlanItems.__init__`, with a regression
test asserting that each native array is read exactly once.

A 520,000-record compare now reaches the populated view in about 10 s with the
native backend (about 8 s on the Python path). The remaining gap is the Stage
4b work: records are parsed natively but still materialized into `Change`
objects twice before the model consumes them.

## Build, CI and rollout (Stage 8)

`native/CMakeLists.txt` is a standalone CMake project with an optional
install target and `QPY_NATIVE_WERROR`. `native/build.sh` still copies the
built module into `src/qpy_rsync/` for local experiments; the generated `.so`
is gitignored. GitHub Actions (`.github/workflows/native-experiment.yml`) runs
the suite with the flag off and on, all three differential harnesses, and
`native/timing_gates.py`. The gates compare native time as a ratio to Python
on the same machine: filter 0.43, plan 0.23, parse 0.34 (all below their
limits).

Debian packaging intentionally remains `Architecture: all` because the
extension is optional and off by default; a native-enabled package would need
`Architecture: any` plus build-dependencies on a compiler, CMake and nanobind.

Rollout plan: two releases with the flag off, then document opt-in, then
consider `auto` once the 520,000-item differential and timing gates stay green.

## What is still needed for a real integration

1. Extend `NativeFilter` with the change/directory flag passes (`_matches`,
   action visibility, ancestor closure), taking explicit decisions as a
   small `(path_id, decision)` set.
2. Add a Python adapter in `qpy_rsync/native.py` with a runtime flag
   (`QPY_RSYNC_NATIVE=0|1|auto`) and a clean fallback to the current Python
   model.
3. Wire `FlatChangeModel._apply_filters` / `_rebuild_visible_rows` to request
   a native result, then emit the same model signals and keep
   `_visible_changes`, aggregates and selection semantics byte-identical.
4. Add `tests/unit/test_native_differential.py` comparing Python and native
   visible rows, change indices and aggregates on a synthetic 520k fixture;
   keep the existing 399 tests as the behavioural oracle.
5. Add timing gates (env-gated, not in the default `-q` run) with thresholds
   relative to a baseline machine.
6. Only then consider the plan kernel and a true "filter list" mode.

## Acceptance for the experiment

- Native path behind a flag; Python path remains default.
- All 399 existing tests green with the flag off and on.
- Differential test proves identical outputs on 520k items.
- Global filter <200 ms native on the user's real tree; single decision
  <80 ms; no change to rsync command lines, profiles or the journal.
