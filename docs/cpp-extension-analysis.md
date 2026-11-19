# Hybrid C/C++ extension analysis for qpy-rsync

**Research report — 2026-11-19.** No files in the working checkout were modified except this report.
**[F]** = verifiable fact from the repository, a timing log, or a measurement made for this report; **[E]** = estimate or judgement.
Companion to `docs/cpp-qt-conversion-analysis.md`, which concluded a full C++ Qt rewrite is not justified.

---

## Executive summary

A hybrid extension is **technically the right shape** for qpy-rsync's remaining hot paths, but it is **not unconditionally worth building**. [E] The measured slow paths are three: the global filter pass (`_apply_filters`, ~818 ms on 520,665 changes; `timing24.txt:183-195`), the excluded-rows rebuild (`refresh_exclusions` / `view.show_excluded`, 430–485 ms; `timing24.txt:123-128,177-182`), and plan construction (`build_execution_plan`, 1.6–2.2 s; `timing24.txt:72,197`). Everything else is already 5–280 ms, and the 45 s rsync dry run is ~90% of the compare cycle and cannot be accelerated. [F]

The decisive constraint is **marshalling, not loop speed**. [E] A local measurement converting 520k × 6-field rows into `ctypes` structures extrapolated to **~1.3 s** — more than the Python filter pass itself; `pybind11`/`nanobind` would be faster (est. 100–400 ms for 6–10 fields including strings) [E] but would still consume a large fraction of the gain. A naive "convert Python objects at each call" extension is therefore a net loss. The only design with defensible ROI is a **persistent native model backend** that owns interned paths and parallel arrays, with Python passing scalars, explicit decisions (k ≪ n) and indices, and receiving positions/slices — never whole object graphs per call. [E]

Recommendation: **nanobind** (pybind11 as fallback) with a runtime feature flag and differential tests. First useful extension: **3–5 person-weeks** [E]; coherent native backend covering filters/rows/aggregates/plan: **10–16 person-weeks** [E]. Condition the go/no-go on dataset growth (≥2M items), a true filter-mode requirement, or a <200 ms interaction SLA; otherwise spend days on Python-side fixes and stay pure Python. [E]

---

## 1. Which paths are worth native acceleration

All "before" numbers below are **[F]** from `timing24.txt` (520,665 changes) unless noted. "After" numbers are **[E]** estimates for optimized C++ with persistent arrays, not measured.

| Path (file:line) | Before [F] | After [E] | Worth it? | ROI |
|---|---|---|---|---|
| `_apply_filters` `flat_change_model.py:888-1118` | 818 ms total; phases: changes 113, directories 177, rows 316, totals 204 (`timing24.txt:184-188`) | 50–120 ms | **Yes — #1** | High: every filter/action change pays this; user-visible typing/click latency |
| `_rebuild_visible_rows` / `refresh_exclusions` `:756-761,1220-1298` | 430–454 ms rebuild, 454–485 ms end-to-end (`timing24.txt:124-128,178-182`); history: 1,053 ms `reset_exclusions` (`timing21.txt:137`) | 40–90 ms | **Yes — #2** | High: same linear scan, simpler than #1, good first target |
| `build_execution_plan` `execution_plan.py:97-218` | plan.loop 1,614–2,230 ms; deleted_sizes 26 ms; total UI plan rebuild 2,284–2,942 ms (`timing24.txt:72-74,197-199`) | 120–300 ms | **Yes — #3** | Medium-high: on Compare/Verify, not every keystroke; large absolute win |
| `_patch_visible_rows` + decision refresh `:1382-1445,1447-1457` | 203–283 ms; sub-costs patch_changes 46–53, patch_rowmap 28–44, patch_stripes 48–76 ms (`timing24.txt:75-122`) | 15–50 ms | **Yes — #4** | Medium: frequent (every checkbox), but affected set is small; native constant factors dominate |
| `decision_filter_lines` `decision_filters.py:19-55` | ~200 ms (user-provided); `verify.filter_file` 1,277 ms including file I/O (`timing24.txt:201`) | 15–40 ms | Yes — #5 | Medium: already cached by plan content (`:58-71`), so only on plan change |
| `search_matches` `flat_change_model.py:1329-1380` | `fnmatchcase` over 520k names = 216 ms [F, synthetic]; plain substring ~35–80 ms [E]; cached per text+layout token | 10–60 ms | Optional | Low-medium: debounced and cached; only matters if true filter mode returns (§7) |
| `ChangeDecisions.reconcile` `changes.py:223-317` | Runs on `set_changes` only (`flat_change_model.py:336`); ~46 MiB for 200k changes [F, prior report] | 30–80 ms | Maybe | Low frequency; fold into native mirror if already built |
| `decision_signature` / `items_fingerprint` `execution_plan.py:86-94,204-209` | 520 decision items json+sha = 0.5 ms [F, synthetic]; 520k-item digest ~50–120 ms [E] | 5–20 ms | No | Low: dwarfed by plan.loop; do not build an extension for this |
| Destination-size prefix sums `destination_sizes.py:22-47` | O(log n) per query; built once per listing | — | **No** | Already optimal for access pattern |
| `index_for_path` / `nearest_visible_path` `:1631-1639,1645-1653` | O(1) dict + O(log n) bisect | — | **No** | Already fast |
| Overview `set_aggregates` `overview.py:206-228` | Normal 67–99 ms; historical rebuild outliers 703–1,096 ms (`timing13.txt:79`, `timing2.txt:1`, `timing17.txt:105`) | Incremental stays 5–70 ms | **No** | Outliers are a *specific rebuild path*, fixable in Python (incremental aggregates already added; CHANGELOG:125-140) |
| Delegates / icons `flat_comparison_view.py:86-209`, `icons.py:159` | Qt painter already native; `sizeHint` fixed (`flat_comparison_view.py:93-98`); QIcons `lru_cache`d | — | **No** | No gain from a Python extension |
| 45 s rsync dry run | 45,000 ms | 45,000 ms | **Impossible** | Dominant cost; only I/O/network/algorithmic rsync changes help |

**Synthetic measurements made for this report [F]** (Python 3.14.4, system interpreter, 520k items): build 520k `Change` dataclasses 1,224 ms; flat-array filter-like loop with bool writes 82 ms; dataclass attribute list-comp 20 ms; `casefold` 520k strings 35 ms; `fnmatchcase` 520k names 216 ms; `encode` 520k paths to UTF-8 44 ms / 15.1 MB; ctypes struct writes (50k rows × 6 fields, scaled) **~1,311 ms**. These show that the 818 ms filter pass is not "Python cannot loop" — the raw loop is ~80 ms; the cost is the hierarchy/aggregate work plus Python object plumbing, which native code can compress but only if the data is already native.

**Priority shortlist [E]:** (1) `_apply_filters` + `_rebuild_visible_rows` as one native "visibility/aggregates" kernel; (2) `build_execution_plan` loop + digest; (3) decision patch; (4) filter-file lines; (5) search index (only with §7). Skip everything already O(log n) or Qt-native.

---

## 2. Extension technology options

Environment facts [F]: Python 3.14.4, SOABI `cpython-314-x86_64-linux-gnu` (`sysconfig`), PySide6 6.10.2 / Qt 6.10.2 in `/usr/lib/python3/dist-packages/PySide6`; `pybind11`, `nanobind`, `Cython`, `cffi` are **not** installed; NumPy is installed but is not a project dependency (`pyproject.toml:13` lists only PySide6). Debian package is `Architecture: all` (`debian/control`) with `pybuild-plugin-pyproject` and `override_dh_auto_test` (`debian/rules`); the launcher unsets `LD_LIBRARY_PATH`/`QT_PLUGIN_PATH` (`qpy-rsync.sh:19-21`).

| Criterion | pybind11 | nanobind | Cython (wrapper) | Cython (compile modules) | cffi / ctypes → .so |
|---|---|---|---|---|---|
| Build complexity | Header-only; CMake or setuptools; `pybind11-dev` on Ubuntu | Header-only; CMake-first; vendor headers or FetchContent | `cython` build dep + .pyx; moderate | Rewrite selected modules in .pyx; can keep Python syntax | Simplest build; hand-written C ABI + `cffi` cdef or ctypes structs |
| Type-conversion overhead | Low; mature casters; ~50–150 ns simple value [E] | Lower; ~20–80 ns value, smaller binary [E] | Low for typed args; Python API still used | Low inside typed code; Python↔C at module edges | Highest: ~1.3 s for 520k×6 via ctypes [F, measured]; cffi faster but still per-field |
| GIL handling | `gil_scoped_release` / `call_guard` | `gil_scoped_release`, better free-threaded story | `with nogil:` requires typed, no-Python code | `with nogil:` works well in typed functions | Must release manually around C calls; callbacks reacquire |
| NumPy / PySide6 coexistence | Fine; no NumPy needed; don't pass QObjects | Same | Same | Same | Same; keep boundary to POD/scalars |
| ABI across Python 3.14 / PySide6 wheels | Stable per CPython minor; rebuild per Python in Debian; PySide6 uses sip, independent | Same; limited API less mature | Same | Same | Stable C ABI + Python minor for the shim |
| Packaging `all` → `any` | Yes: `${shlibs:Depends}`, `python3-dev`, compiler build-deps | Yes (vendor headers) | Yes | Yes | Yes, simplest runtime deps |
| Debug / profiling | C++ symbols, gdb, ASan/UBSan, `perf`; py-spy sees one frame | Same | Generated C + line directives; symbol maps needed | Same | C symbols; harder to map to Python semantics |
| Test integration | Import in pytest like any module; differential tests straightforward | Same | Same | Same | Same |

**Recommendation: nanobind for a greenfield extension; pybind11 if distro-packaging convenience and documentation depth dominate.** [E] Both avoid NumPy entirely (no array algebra in these paths) and both coexist with PySide6 as long as the boundary carries POD, interned path ids, indices and small buffers — not QObjects. Both require flipping Debian to `Architecture: any` with `python3-dev`/compiler build-depends and `${shlibs:Depends}`; this is the same flip a full C++ port needs, but only once. Avoid ctypes for the hot boundary — the measured 1.3 s marshalling cost alone exceeds the Python filter pass. Avoid full-module Cython compilation: it would fragment the very Python code that the 399 tests exercise and reintroduce the port risk the previous report rejected. [E]

---

## 3. The hard part: data marshalling

**Problem.** The hot paths operate on 520k `Change` dataclasses (`core/changes.py:26-40`), `FlatRow` objects (`flat_change_model.py:155-178`) and dicts of aggregates. The model already mitigates the *Python-side* cost with parallel arrays (`:295-311`): `_change_paths`, `_change_names`, `_change_sizes`, `_row_paths`, `_row_is_dir`, `_row_dir_index`, etc. Those arrays are exactly the shape a native backend wants — the mistake would be rebuilding them on every call. [F]

**Cost of per-call conversion [E].** Measured lower bound: ctypes 520k×6 field writes ≈ 1.3 s [F]. A pybind11/nanobind `std::vector<Row>` with 6–10 fields including two strings: ~100–400 ms [E] (one UTF-8 encode of all paths is 44 ms [F], so ~50–150 ms of pure copying is unavoidable). That is 12–50% of the 818 ms filter budget spent before doing any work, and it would also duplicate 15+ MB of strings per call. Verdict: **never marshal O(n) on a hot call.**

**Proposed API boundary — persistent native mirror.** One `NativeComparison` object, created once per `set_changes` (`flat_change_model.py:332-351`), owns:

- interned path table: `vector<string>` + `unordered_map<string_view, uint32_t>`; casefolded names/paths stored once (mirrors `_row_names_folded`/`_row_paths_folded`, `:310-311`);
- CSR-style arrays: sizes, action/kind codes, directory index, parent id, child adjacency, change index, excluded/visible/path_ok/action_ok bits;
- directory table with subtree aggregates (mirrors `FlatDirectory`, `:122-152`);
- `visible_rows: vector<uint32_t>` and `visible_position_of_row: vector<int32_t>` (mirrors `:291-292`);
- decision map keyed by interned path id with a decision generation counter; explicit decisions only (k ≪ n).

Hot calls take only scalars/small sets and return positions or compact buffers:

```
load(paths, names, actions, kinds, sizes, parents) -> handle        # once, O(n)
set_decisions([(path_id, decision), ...]) -> decision_generation    # O(k)
apply_filters(pattern, flags, actions_mask, collapsed_ids,
              show_excluded, conflicts_only) -> generation          # O(n) in C++
row_count() -> int
visible_positions(row_ids[]) -> positions[]                         # O(k)
visible_rows_slice(start, count) -> buffer[int32]                   # only painted rows
search(query, query_generation) -> buffer[int32]                    # §7
aggregates_snapshot() -> small dict only for folders that changed   # O(k)
```

**Keeping Qt model semantics.** `FlatChangeModel` stays a Python `QAbstractTableModel`. `rowCount()` (`:1611-1612`) returns `native.row_count()`; `index_for_path` (`:1631-1639`) and `nearest_visible_path` (`:1645-1653`) map through native positions then call `createIndex`; `data()` (`:1676+`) continues to serve Display/Decoration/CheckState/roles from a *small* Python cache for the currently painted slice (~50 rows × 3 panes), not from 520k objects. Materialize `_visible_changes` lazily only when a caller asks (`visible_changes()`, `:1604-1606`) — most frames never need it. Because QModelIndex is positional and roles are unchanged, `QItemSelectionModel`, `QPersistentModelIndex`, `scrollTo`, the three linked panes, and all delegates (`flat_comparison_view.py:86-209,1237-1253`) keep working untouched as long as Python still emits `begin/endResetModel` and bumps `layout_token` (`:1118`). [E]

---

## 4. Threading and the GIL

- **GIL release is possible** for every hot kernel in §1: `apply_filters`, aggregates, plan loop, filter-file generation, search. Use `nb::gil_scoped_release` / `py::gil_scoped_release` around code that touches only native arrays. Ensure no Python object or `Signal` is accessed inside the released region; copy results into native buffers first. [E]
- **Qt model access must stay on the GUI thread.** `rowCount`, `data`, `index`, `begin/endResetModel`, `layoutChanged` and all signal emissions are GUI-thread-only. PySide6 emits Qt warnings for cross-thread model access, and the test harness sets `QT_FATAL_WARNINGS=1` (`qpy-rsync-test.sh:8`), so violations become hard failures. [F + E]
- **Can run in a worker:** filter/visibility computation, aggregates, `build_execution_plan`, prefix sums, decision-filter text, search index construction. Pattern: worker computes a new immutable `NativeComparison` snapshot or result buffer; on completion a `QueuedConnection` delivers a small signal to a GUI-thread slot that swaps the handle and emits one model reset. Generation counters (decision/filter/layout) discard stale results. [E]
- **Dangers:** never share a QObject across threads; don't call PySide6 from a released-GIL region; ensure `QApplication` lives on the GUI thread; avoid deadlocks when native code calls back into Python (use no Python callbacks in hot loops); keep pointers to Python-owned buffers only inside the GIL-held window. A `QFuture`/`QThreadPool` + Python `signal` bridge is acceptable but adds lifecycle complexity — prefer a plain `QThread` with a single result signal. [E]

---

## 5. Effort and timeline

Single experienced developer, Python GUI and 399 tests unchanged [E]:

| Deliverable | Person-weeks |
|---|---|
| Characterization harness + differential tests + golden fixtures | 0.5–1 |
| Build system (pybind11/nanobind), Debian `all`→`any`, CI smoke | 1–2 |
| **First useful extension:** native visibility kernel (`_apply_filters` + `_rebuild_visible_rows`) behind flag | **3–5 total** |
| Decision patch + aggregates mirror | 2–3 |
| Plan loop + fingerprint + filter-file lines | 2–3 |
| Search index / true filter mode (§7) | 2–4 |
| Threading, snapshot swapping, generation counters | 2–3 |
| Hardening, docs, staged rollout | 1–2 |
| **Coherent native backend (all above)** | **10–16 total** |

**Risks [E]:** mixed-language build and ABI churn across Python minors; two debugging worlds; stale-snapshot/use-after-swap bugs; PySide6 thread affinity; memory ownership of interned strings; regression of subtle filter semantics (ancestor inclusion, folds, conflicts) that the existing 399 tests encode; Debian rebuild/test integration. **Fallback:** keep the Python implementation as the default behind `QPY_RSYNC_NATIVE=0` (or `auto` with opt-in) for at least two releases; any native path can be disabled per-call. The first release should be *identical behaviour, slower-or-equal* — never a forced cutover.

---

## 6. Testing, profiling, debugging

- **Keep 399 tests meaningful.** `./qpy-rsync-test.sh -q` (49 test files, 399 tests [F]) runs unchanged with the native flag off, so it remains the behavioural oracle. Add a `tests/unit/test_native_differential.py` that builds one synthetic 520k dataset, runs Python and native backends, and asserts byte-identical `_visible_rows`, `_visible_change_indices`, `_aggregate_counts`, `search_matches`, `build_execution_plan` items/summary/fingerprints, and `decision_filter_lines` output. Seed existing fixtures: `test_flat_filtering.py`, `test_execution_plan.py`, `test_decision_filters.py`, `test_overview_filtering.py`, `test_flat_comparison_view.py`. [F + E]
- **Timing gates.** `backend/diagnostics.py:31-49` already provides `debug_timing`/`timed` with `QPY_RSYNC_TIMING`; production logs are in `timing*.txt`. Add env-gated perf tests (not part of the default `-q` run) with thresholds on the 520k fixture: full filter <200 ms native / <1 s Python, single decision <80 ms, exclude toggle <150 ms, plan <400 ms [E]. Make CI fail on *ratio to a baseline machine*, not absolute ms, to avoid hardware noise. [E]
- **ASan/valgrind.** Build with `-g -fno-omit-frame-pointer -fsanitize=address,undefined`; run the offscreen smoke test under `ASAN_OPTIONS=detect_leaks=1` with a suppression file for CPython/PySide6 allocations; run `valgrind --tool=memcheck` on a short headless session. TSan is not practical with Qt/PySide6; skip it. This is a genuine advantage over pure Python, but applies only to the extension. [E]
- **Symbolized profiles.** `perf record -g --call-graph dwarf` on a release build; py-spy will show the extension as a single frame, so use `perf`/hotspot for native frames and keep the `QPY_RSYNC_TIMING` phase markers as the mixed-language correlation point. [E]
- **Staged rollout.** (0) flag off, both implementations shipped; (1) opt-in native filters only; (2) native filters + plan default-on after two green releases; (3) remove Python path only if maintenance cost outweighs the fallback value. [E]

---

## 7. Can a native backend bring back a true filter mode?

**Current state [F].** The model still implements path filtering: `set_path_filter` (`flat_change_model.py:669-685`) sets `_pattern`/`_pattern_is_glob`, and `_matches` (`:857-886`) does name-vs-path, trailing-slash directory and `fnmatchcase` matching; `_apply_filters` honours it at `:897,916-945,960-999`. But commit `81b1a44` ("replace path filter with search") rewired the UI: the `filter_edit` + 300 ms debounce + `set_path_filter` call was replaced by `search_edit` + jump-only `find_next`/`_run_search` (`flat_comparison_view.py:1279-1320`). `set_path_filter` is now called only by tests (`test_flat_filtering.py`, `test_flat_comparison_view.py`). The reason recorded in that diff and CHANGELOG:680-719 is cost — a global filter on 520k items was a visible pause.

**Compute feasibility with native backend [E].** Yes, comfortably. With the persistent arrays of §3, filtering is one linear pass over interned, pre-folded strings: substring scan ~10–30 ms, glob via `fnmatchcase`-equivalent or compiled automaton ~30–80 ms for 520k (Python `fnmatchcase` alone is 216 ms [F]; native `std::string_view` is typically 5–10× faster [E]). Ancestor inclusion, excluded-state checks, aggregate collection and visible-row production happen in the same pass (the Python code already fuses them at `:1010-1117`), so total compute is ~30–120 ms; add 50–150 ms for Qt model reset/repaint → **end-to-end 100–300 ms**, under the 1 s target. [E]

**Required data structures [E]:**
- canonical interned path keys + precomputed casefolded name/path (already present as Python arrays at `:310-311`);
- an inverted index (token → posting list of row ids) for fast substring/word queries; for globs, candidate narrowing by trigram prefix or a compiled glob automaton over folded names — optional at 520k, valuable at 5M+;
- generation counters for filter query, decisions, collapsed folds and layout; stale results are discarded before being published;
- ancestor closure bits (`directory.path_ok/action_ok`, `:910-999`) computed in the same pass, so kept parents and faded directories behave exactly as today;
- selection anchoring: store selected *paths*, map to row ids, reselect nearest visible path via existing semantics (`:1645-1653`) when a selected row is filtered out;
- folds: a filter temporarily overrides collapsed state (`:899-901`) and clearing it restores the exact prior fold set;
- decisions/overview: decisions are keyed by path (`changes.py:65-77`) so filtering never touches them; aggregate counts feed `set_aggregates` unchanged (`overview.py:206-228`).

**UI/UX pitfalls [E]:** distinguish "filter the view" from rsync include/exclude rules (the old tooltip explicitly said so); debounce vs immediate feedback (120–150 ms native, keep 300 ms for Python fallback); glob-vs-substring ambiguity (`*` in a filename); preserve scroll position, selection and folds on clear; show a match/visible count; disable or clearly scope filtering on stale comparisons; never let the filter affect the execution plan (it does not today).

**Recommended design [E]:** restore the filter field with an explicit "Filter list" toggle next to the existing search (keep both modes), route it through `set_path_filter` semantics but evaluate in the native kernel with generation counters, and keep jump navigation as the default for plain search. **Acceptance criteria:** (1) <250 ms target / <1 s hard limit end-to-end on 520k for name, path and glob queries; (2) decisions, folds, selection and overview totals byte-identical before/after a filter round-trip; (3) clearing restores exact prior view including scroll; (4) 399 tests + differential tests green; (5) no change to plan, rsync rules or journal; (6) works under the existing stale-comparison policy. If these hold, a true filter mode becomes practical and is arguably the strongest *product* justification for the extension — stronger than raw ms. [E]

---

## 8. Final recommendation

**Conditional hybrid, not a default yes.** [E] Build the extension only if at least one of these holds: (a) datasets grow to ≥2M items (4× today), (b) a true filter mode becomes a product requirement, or (c) a <200 ms interaction SLA is adopted. If none hold, stay pure Python and spend days — not weeks — on the known outliers: incremental aggregates for `show_excluded`, precomputed canonical/folded keys (already largely done), text-extent caching, and timing gates in `qpy-rsync-test.sh`. That captures most of the interactive win with none of the ABI/debugging cost.

If the green-light conditions are met, the scope should be the narrow native visibility/aggregates kernel first (3–5 person-weeks [E]), with nanobind, a persistent native model backend, differential tests and a runtime flag; expand to plan/filter-file/search only after that kernel proves itself. A full C++ Qt rewrite remains unwarranted: it would still leave the 45 s rsync dominant and would discard the 399-test safety net. [E]

**Conditions that would change the answer to "definitely hybrid":** 5M+ items or a hard memory cap; a shipped filter mode; profiling after Python optimization still showing >500 ms in `_apply_filters`; or a strategic need for framework independence (which would instead favour the full rewrite). **Conditions that would change it to "definitely stay Python":** PySide6/Python ABI churn making per-minor rebuilds costly, loss of key maintainers comfortable with C++, or measurements showing marshalling ≥ native savings.
