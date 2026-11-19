# Native backend: implementation stages

Experiment branch `native-extension-experiment`. This is the execution plan for
the eight workstreams in the final recommendation of
`cpp-extension-analysis.md`. Each stage ends with a checkpoint that must pass
before the next one starts.

## Guiding constraints

- One shared object (`_qpy_native`), one build. No per-call O(n) marshalling.
- The Python GUI and the 408 pytest tests are the behavioural oracle.
- Python implementation stays the default behind `QPY_RSYNC_NATIVE=0|1|auto`.
- GUI-thread only for Qt model calls; native kernels may run in a worker with
  generation counters discarding stale results.

## Stages

1. **API boundary — checkpoint: persistent mirror, differential harness.**
   `NativeComparison` owns interned paths, folded keys, flat arrays, directory
   table, visible-row map and decision generation. Python passes scalars,
   `(path_id, decision)` pairs and small buffers. A differential test fixture
   builds a synthetic comparison and asserts Python vs native aggregates and
   visible rows byte-for-byte.

2. **Full filter kernel — checkpoint: 520k filter <200 ms, differential green.**
   Move `set_path_filter`/`_matches`, action visibility, ancestor closure,
   excluded/fold/conflict flags and aggregate collection into native code.

3. **Qt model wiring — checkpoint: 399+ tests green with flag on and off.**
   `FlatChangeModel` stays a `QAbstractTableModel`; `rowCount`, `index`,
   `data`, selection, scroll, folds and delegates unchanged. Serve the painted
   slice from a small Python cache. Python fallback remains default.

4. **Native compare parser — checkpoint: parse <1 s end-to-end on big tree.**
   Feed stdout chunks to native arrays directly; avoid constructing 520k
   Python `Change` objects. The existing `parse_records()` benchmark (0.25 s
   vs 1.66 s) is the starting point.

5. **Native plan kernel — checkpoint: plan <400 ms, fingerprint identical.**
   `build_execution_plan`, `decision_signature`, `items_fingerprint`,
   `decision_filter_lines`.

6. **Search / filter mode — checkpoint: <250 ms filter round-trip.**
   Native inverted/canonical index, generation counters, selection/fold/overview
   preservation; restore the “Filter list” UI toggle.

7. **Threading and GIL — checkpoint: no stale publication under rapid edits.**
   Release GIL only in array-only kernels; publish snapshots via a queued
   signal on the GUI thread; never call Qt from a worker.

8. **Build, packaging, rollout — checkpoint: CI + flags + docs.**
   CMake subproject, Debian `Architecture: any`, build-depends, CI matrix,
   env-gated timing regressions with ratio-to-baseline thresholds, ASan /
   valgrind, docs. Ship flag-off for two releases before default-on.

## Current status

- **Stage 1 done** (`cb8628b`): persistent `NativeComparison` mirror and a
  nine-scenario differential harness in `native/check_model.py` comparing
  visible rows, the visible change set and per-directory aggregates
  byte-for-byte against `FlatChangeModel`.
- **Stage 2a done** (this commit): the native kernel now computes change
  visibility, directory ancestor closure, faded flags and the aggregates
  itself. `native/check_model.py` runs ten scenarios, seven through the
  native flag kernel; `native/bench_filter.py` checks a 520,000-item tree
  byte-for-byte.
  - Measured on 520k changes / 550,590 rows / 30,590 folders: Python
    `_apply_filters` 620 ms (all), 328 ms (updates-only), 602 ms (creates);
    native `filter()` 10.1 ms, 7.3 ms, 10.3 ms — a 45–61x speedup and well
    under the 200 ms target.
  - Still in Python: path-pattern matching (`_matches`, glob, directories-only)
    is deferred to Stage 6, and `row_excluded` / `folded_parent` are passed as
    per-row flags (empty buffers on the common path, so no O(n) marshalling).
- Stages 3–8 not started.
