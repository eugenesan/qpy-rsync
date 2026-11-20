# Native backend: implementation stages

Experiment branch `native-extension-experiment`. This is the execution plan for
the eight workstreams in the final recommendation of
`cpp-extension-analysis.md`. Each stage ends with a checkpoint that must pass
before the next one starts.

## Checkpoint 1 — metadata path (A + B), done

- **A:** `FlatChangeModel.merge_destination_metadata` updates the existing
  dict in place, builds the size index once, and recomputes destination sizes
  only for changes whose path or an ancestor appears in the new listing. The
  native mirror gets a `set_dest_sizes` update instead of a full rebuild.
- **B:** `gather_destination_metadata` now uses one unfiltered
  `rsync --list-only` listing (profile copy with `filters = []`, preserving
  the remote-shell argument) instead of a filtered listing plus a fallback.
  `QPY_DEST_METADATA_TWO_PASS=1` restores the old path for A/B measurement.
- Evaluation: `native/bench_metadata.py` measures the full model path at
  520k changes / 100k metadata entries: **1158 ms -> 394 ms (2.94x)**.
  `timing_gates.py` adds a metadata gate. 419 tests pass in both modes.
  The listing itself needs A/B on the real remote tree; the env flag exists
  for that and the single-pass path wins one rsync invocation / SSH handshake.

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
- **Stage 3 done** (this commit): `FlatChangeModel` uses the native kernel
  behind `QPY_RSYNC_NATIVE`. Unset or `0` keeps the pure-Python path; `1`
  requires the extension (falling back with a debug message if absent), and
  `auto` uses it when present. Qt roles, selection, folds, exclusions,
  aggregates, subtree totals and the incremental refresh paths are preserved.
  The whole suite passes with the flag off, on and `auto` (411 tests).
  - End-to-end on 520,000 changes: filter pass 326 ms (Python) → 150 ms
    (native); `set_changes` 4.24 s → 4.75 s (the one-time mirror costs more
    than it saves until the parser is native too, Stage 4).
  - Path-pattern filters still use the Python path; search is Stage 6.
- **Stage 4 done** (this commit): `CompareService` can accumulate parsed
  records in native arrays behind the same flag, and `ParseResult.changes`
  becomes a lazy `Sequence[Change]`. The parser now produces every `Change`
  field (link target, reason, deletion size/time, kind, action), and
  `native/check_parse.py` compares full records plus the malformed-record
  error against `backend/rsync_parser.py`.
  - Measured on 520,000 records: Python `parse_record` 1.56 s; native
    accumulation 0.56 s; lazy `Change` materialization 1.01 s. The parse
    phase logged by the application drops by about 1 s because materialization
    happens later, but the total time to the populated view is unchanged.
  - **Stage 4b remains:** teach `FlatChangeModel` to consume native arrays
    directly so the 520,000 `Change` objects are never created.
- **Stage 5 done** (this commit): `build_execution_plan` can use a native
  kernel for the item loop, summary counters and the items-fingerprint byte
  stream. Decision inheritance and the deleted-size lookup stay in Python.
  `native/check_plan.py` compares items, summary and fingerprint byte-for-byte
  in four decision scenarios; a pytest parity test covers the integrated path.
  - Measured on 520,000 changes: plan 1,386 ms (Python) → 466 ms (native) with
    an identical `items_fingerprint`.
  - `decision_filter_lines` (~200 ms) is not moved yet; the analysis rates it
    lower value because it is cached by plan content (Stage 5b).
- **Stage 6 done** (this commit): native glob/substring pattern filtering
  (`filter_pattern`), a native `search_rows` index, and the restored
  **Filter list** toggle in `FlatComparisonView` (shown only with the native
  backend). `native/check_model.py` now runs six pattern scenarios, including
  `*`, `?`, `[...]`, slash paths and directory-only patterns, all matched
  byte-for-byte against `FlatChangeModel`.
  - Native glob search on 520,000 rows: 207 ms (Python) → 42 ms.
  - pytest parity covers search and the filter-mode toggle; all 415 tests pass
    with the flag off and on.
- **Stage 7 done** (this commit): every array-only kernel releases the GIL
  (`apply`, `filter`, `filter_pattern`, `search_rows`, `build_plan_arrays`,
  `parse_records`). The model now snapshots native results into a
  `_NativeSnapshot` carrying a generation and publishes it through
  `_publish_native_snapshot`, which discards stale generations. A regression
  test verifies the discard. All 416 tests pass in both modes.
  - The queued QThread worker itself is not wired up: the current kernels are
    fast enough that GUI-thread execution stays under 1 s. The snapshot and
    generation boundary is in place so a worker can be added without changing
    the publication path.
- **Stage 8 done** (this commit): CMake is a real subproject with an install
  target and optional warnings-as-errors; `.github/workflows/native-experiment.yml`
  runs the Python suite, the native suite, the three differential harnesses and
  the environment-gated timing gates; `native/timing_gates.py` compares ratios
  to the Python path on the same machine (filter 0.43, plan 0.23, parse 0.34 —
  all passing).
  - Debian packaging deliberately stays `Architecture: all`. The extension is
    opt-in and off by default, so shipping the Python-only package must not
    require a compiler or nanobind. A native-enabled package is a separate
    decision for a release that makes the backend default-on.
  - Rollout: keep the flag off by default for two releases; then opt-in via
    settings/`QPY_RSYNC_NATIVE=1`; switch to `auto` only after the full
    520,000-item differential suite and timing gates stay green.
- **All eight stages have an implementation checkpoint.** Remaining work is
  the Stage 4b model refactor, a queued QThread worker, `decision_filter_lines`,
  and the release/packaging decision above.
