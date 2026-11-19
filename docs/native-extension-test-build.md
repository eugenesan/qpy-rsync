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
