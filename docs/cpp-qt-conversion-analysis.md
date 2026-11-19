# C++ / Qt conversion analysis for qpy-rsync

**Research report — 2026-11-19.** No files in the working checkout were modified except this report.
Throughout, **[F]** marks a verifiable fact from the repository or current upstream docs, and **[E]** marks an estimate or judgement.

---

## Executive summary

A full C++ Qt rewrite is technically feasible — the app is a thin Qt Widgets frontend over an external `rsync` process — but it is **not justified by performance**. [E] The measured 45 s rsync dry run dominates a ~50 s compare cycle; every interactive action is already 0.07–1.1 s, and the worst outliers are algorithmic rebuild paths that can be fixed in Python in days. [F] The codebase is 17,227 lines of Python plus 7,850 lines / 399 tests, with ~48% of source in three GUI modules (`main_window.py` 4,358 lines, `flat_change_model.py` 2,209, `flat_comparison_view.py` 1,744). [F] A clean-room port is ~15–21 person-months for one developer [E], must reproduce hand-drawn icons, delegates, shortcuts and Breeze styling exactly, and would require re-writing all 399 pytest tests as Qt Test/CTest cases. **Recommendation: stay Python; optimize the hot paths; consider a narrow C++ extension only if the dataset grows 5–10×.** [E]

---

## 1. Feasibility and complications

**[F] What exists today:** 58 Python modules, 17,227 source lines, zero C++/CMake files. The sole runtime dependency is `PySide6>=6.7,<7` (`pyproject.toml`); dev tools are pytest, pytest-cov, ruff and strict mypy. The architecture is cleanly layered (`gui`, `core`, `backend`, `services`, `storage`; `docs/design.md` §12): argument vectors to `QProcess`, never a shell; a versioned rsync `--out-format` protocol with the `|qpy-rsync|` field token; a flat `QAbstractTableModel` (`flat_change_model.py`) shared by three `QTableView` panes; and `@dataclass(slots=True, frozen=True)` value types in `core/changes.py`.

**[F] Why a port is mechanically straightforward:** every Qt concept already maps 1:1 to C++ Qt — `QAbstractTableModel`/`QAbstractItemModel`, `QStyledItemDelegate`, `QProcess`, `QSettings`, `QSystemTray`-style notifications, signals/slots. Qt 6 itself moved to CMake (`doc.qt.io/qt-6/qt6-buildsystem.html`), and `qt_add_executable()` + `qt_standard_project_setup()` (AUTOMOC) are the documented path. Licensing is not a blocker: Qt is LGPLv3/GPLv3-or-commercial (`doc.qt.io/qt-6/licensing.html`) and Qt Widgets (qt6-base) is LGPLv3, compatible with the project's GPL-3.0-or-later; only a handful of optional modules are GPL-only and none are used.

**[F] Main complications:**
- **Hand-drawn UI assets in code.** `gui/icons.py` (720 lines) paints every icon with `QPainter` on a 16×16 grid rendered at 64 px with `lru_cache`; there are no `.svg`/`.png` action assets. `action_colours.py` holds user-editable colours. These drawing routines must be ported line-for-line or the visual identity changes.
- **Non-trivial model/view semantics.** `flat_change_model.py` has 120+ methods: custom roles (`PATH_ROLE`, `STRIPE_ROLE`, `EXCLUDED_ROLE`, `CONFLICT_ROLE`), patch-based incremental refresh (`_patch_visible_rows`, `_patch_folded_rows`), undo/redo snapshots, decision inheritance and conflict reconciliation. `QModelIndex` lifetime, persistent indexes, and `begin/endResetModel` vs fine-grained signals are the classic source of native crashes.
- **Process/crash sensitivity.** `CHANGELOG.md` records multiple native Qt crash fixes, env sanitization (`PYTHONPATH`, `QT_PLUGIN_PATH`, …), `SSH_ASKPASS`, `setsid`, process-group pause/cancel, and X11/Wayland askpass handling. That is hard-won behaviour to re-derive.
- **State compatibility.** Profiles are JSON with `schema_version`, legacy migrations (old `delete` boolean, legacy backup mode) and `tools/convert-profiles.py`; settings are INI via `QSettings` with base64 workarounds for the KDE INI parser (`storage/settings.py`). A port must read both formats byte-for-byte.

**[F] FFF context:** the prior `/home/user/Develop/src/freefilesync/qpy-rsync-fff-analysis.md` shows FreeFileSync is C++ but wxWidgets-based, has no rsync backend, and its last GPL version is v12.5. Its performance ideas (one-pass filtered view, O(1) row maps, generation counters, ~25 ms progress throttle, priority icon prefetch) are **already implemented** in `flat_change_model.py` / `flat_comparison_view.py`. A C++ port would gain no architectural novelty — only raw loop speed.

---

## 2. Development, testing, profiling, debugging

| Area | Current Python workflow | After a C++ port |
|---|---|---|
| Edit/run | No build step; `./qpy-rsync.sh`, `PYTHONPATH=src /usr/bin/python3 -m qpy_rsync.app` | CMake configure + compile (+ moc/uic/rcc); Ninja incremental builds, ccache strongly advised |
| Tests | `./qpy-rsync-test.sh -q` → 399 pytest tests, `QT_QPA_PLATFORM=offscreen`, `QT_FATAL_WARNINGS=1`, no synthetic pointer driving — widgets built and driven directly | Port all 399 cases to Qt Test classes + CTest; offscreen via `-platform offscreen` / `QTEST_QPA_PLATFORM=offscreen` (Qt docs: offscreen fully supported on X11). `QTest::mouseClick`/`keyClick` would introduce pointer-driven tests the current suite deliberately avoids |
| Static analysis | strict mypy, ruff | Compiler warnings (`-Wall -Wextra -Wpedantic`), clang-tidy, include-what-you-use; no mypy equivalent for runtime semantics |
| Profiling | `perf_counter` instrumentation built in (`backend/diagnostics.py`: `timed`, `debug_timing`, `QPY_RSYNC_TIMING`), cProfile, py-spy | `perf`, `heaptrack`, `valgrind --tool=callgrind`, `-ftime-trace`, Qt Creator profiler |
| Debugging | `PYTHONFAULTHANDLER=1`, Python tracebacks | gdb/lldb via Qt Creator, **plus** ASan/UBSan/TSan (`-fsanitize=address,undefined,thread`) and valgrind memcheck/helgrind — genuinely new capability for catching lifetime bugs |
| CI | One script, system Python, no build matrix | Build matrix (compiler × Qt version × sanitizer), longer jobs, ccache; CDash/CTest reporting available |

**[E] Net effect:** the day-to-day loop gets slower (compile latency, moc, link) and the test suite is a multi-person-month port with real risk of losing coverage during the transition. Debugging memory errors improves, but the app is memory-safe by construction today. Build times for ~17k lines equivalent: minutes for a cold build, seconds incremental — acceptable, but objectively worse than zero.

---

## 3. System dependencies on Ubuntu

**[F] Current runtime (from `docs/installation.md`, `debian/control`, verified in this environment):** Python 3.14.4 / PySide6 6.10.2 / Qt 6.10.2; packages `python3-pyside6.qt{core,gui,widgets}`, `rsync`, `openssh-client`, `util-linux` (`setsid`), a graphical askpass helper (`ksshaskpass`), optional `kdiff3 | meld | diffuse`. Debian source package is `Architecture: all`.

**[F] Upstream:** Ubuntu 26.04 (resolute) ships `qt6-base-dev` 6.10.2+dfsg-7, CMake 4.2.x, GCC 15.x (verified locally: cmake 4.2.3, g++ 15.2.0). Qt 6 requires C++17 or newer; C++20 is a sensible target for new code.

**[E] A C++ build would additionally need:**

```bash
sudo apt install build-essential cmake ninja-build pkg-config \
  qt6-base-dev qt6-base-dev-tools qt6-base-private-dev \
  libxcb1-dev libxcb-cursor-dev libxkbcommon-x11-0 libxkbcommon-dev \
  libgl1-mesa-dev libfontconfig1-dev
```

`qt6-base-private-dev` only if private headers are used; `qt6-tools-dev`/`linguist-qt6` for Designer/translation tooling; `qt6-5compat-dev` only if legacy APIs are retained. **ICU** (`libicu-dev`, Unicode collation/text) and **OpenSSL** (`libssl-dev`, TLS) are pulled transitively by Qt's Core/Network modules and are *not* app-level needs here — the app delegates SSH to OpenSSH and does no TLS itself. Packaging flips to `Architecture: any` with `${shlibs:Depends}` and a build-depends on `qt6-base-dev`; the Breeze Qt style plugin must remain available to preserve look-and-feel. FFF-specific libraries (wxWidgets, curl, libssh2, PuTTY) are irrelevant to this design.

---

## 4. Performance: what C++ would actually fix

**[F] Measured on a 1.2M-item tree (~526,659 changes), `timing26.txt`:** global filter refresh **760.9 ms**; single-decision refresh **~70–103 ms** (of which `patch_changes` ~15 ms, `patch_rowmap` ~8 ms, `patch_stripes` ~12 ms, `decision_rows` ~58–88 ms); fold/expand **~120 ms**; overview update typically **5–70 ms** but two rebuild paths hit **706 ms**; `excluded_rows_rebuild` **356–420 ms** and `view.show_excluded` up to **1,099.8 ms**. The rsync dry run is **~45 s**. A synthetic measurement here: 200k `Change` objects cost ~45 MiB and `ChangeDecisions.reconcile()` another ~46 MiB — extrapolating to ~240 MiB for 526k *before* rows/directories/Qt overhead; **[E] full model likely ~400–600 MiB in Python vs ~150–250 MiB in C++ (2–4× better).**

**[E] What C++ fixes:** the 0.76 s filter loop and 0.36–0.42 s exclusion rebuild become ~20–80 ms with `std::vector`/`std::string_view`, precomputed canonical keys and reserved containers; decision patch paths drop under ~10 ms; fold/expand becomes near-instant; overview rebuild outliers disappear. Per-cell Python `data()` callback overhead (~hundreds of calls per repaint) vanishes, though Qt's native painter is already shared by PySide6 so paint throughput itself barely changes. Memory drops 2–4×.

**[F] What is already fine / cannot change:** Qt painting is native in both cases; incremental patching, O(1) row maps and generation counters are implemented; normal overview updates (5–70 ms) and decisions (~0.1 s) already meet the <1 s goal. **No C++ port can speed up the 45 s external rsync** — it is ~90% of wall-clock and unchanged.

**[E] Blunt assessment:** a full rewrite to fix sub-second interactions while leaving the 45 s bottleneck untouched is poor engineering economics. The 706 ms/1.1 s outliers are a *specific rebuild path*, not a language limit: fix incremental aggregate updates for `show_excluded`, precompute canonical match/sort keys, cache text extents (the FFF report's ideas), and add timing regression thresholds to the suite — days of work, not person-months. A **hybrid** C++ extension replacing only the filter/row-map inner loop is the only rewrite variant with defensible ROI, and only if item counts grow 5–10× (5M+) or memory becomes a hard cap; it adds a mixed-language build, ABI/bindings maintenance and two debugging worlds. **Verdict: optimize Python first; keep C++ as a contingency.**

---

## 5. Effort, risk and staged migration

**[E] Single experienced developer, clean-room port, parity required:**

| Module group | Source lines | Person-months |
|---|---:|---:|
| `core` (changes, decisions, plan, endpoints, validation, units…) | ~1,500 | 1.0–1.5 |
| `backend` (command, parser, inventory, QProcess, filters, ssh) | ~1,400 | 1.0–1.5 |
| `services` (compare, sync, verification, tools, progress) | ~1,300 | 1.0–1.5 |
| `storage` (profiles/settings + migration compatibility) | ~250 | 0.5–0.75 |
| `gui` flat model + comparison view | ~3,950 | 2.5–3.5 |
| `gui` overview/delegates | ~750 | 0.75 |
| `gui` dialogs (sync, profile, settings, help, filter, tools…) | ~2,400 | 1.5–2.0 |
| `main_window.py` | 4,358 | 2.5–3.5 |
| CLI, app entry, desktop integration | ~500 | 0.5 |
| Test port: 399 tests / 7,850 lines → Qt Test + CTest | — | 2.0–3.0 |
| Build system, CI, Debian packaging (`all` → `any`) | — | 0.75–1.0 |
| UI/UX parity tuning and acceptance | — | 1.0–1.5 |
| **Total (before contingency)** | **17,227** | **~14–20 PM** |

Add 10–20% contingency → **~15–21 person-months (~1.5 years) for one developer; ~6–9 months with three developers** minus coordination losses. [E]

**High-risk areas [E]:** (1) Qt model/view rewrite — signal timing, `QPersistentModelIndex`, reset ranges; (2) signal/slot semantics — queued vs direct, thread affinity, lifecycle; (3) profile/settings compatibility — JSON schema versions and the KDE INI base64 quirks; (4) process handling — env sanitization, askpass, `setsid`, pause/cancel and the recorded native crashes; (5) packaging — `Architecture: any`, Qt runtime plugin dependencies; (6) tests — 399 cases ported with no synthetic-pointer precedent.

**Staged path with checkpoints [E]:**
0. **Characterize.** Freeze UI, capture golden screenshots and 526k-item timing baselines; 399 tests green. *Checkpoint: behavioural contract + baselines committed.*
1. **Skeleton.** CMake + Ninja + Qt Test/CTest + headless CI. *Checkpoint: offscreen QTest job green.*
2. **Headless core.** Port `core`/`backend`/`storage`/`services`; drive via CLI against fixture rsync output. *Checkpoint: byte-identical command vectors, plan and profile round-trips.*
3. **Hot model.** Port `FlatChangeModel`; differential-test row maps, filters, aggregates against Python on 526k items. *Checkpoint: identical outputs; <80 ms filter.*
4. **Views and dialogs.** Port delegates, panes, overview, dialogs, `main_window`; screenshot diff at each step. *Checkpoint: side-by-side visual parity.*
5. **Process/sync parity.** Re-run smoke tests and native-crash scenarios. *Checkpoint: identical journal and verification semantics.*
6. **Cutover.** Debian packaging, install test, perf gate (<1 s all actions), then dual-run one release before removing Python. *Checkpoint: all gates green.*

---

## 6. UI/UX preservation

**Must replicate exactly [F]:** three synchronized `QTableView` panes sharing one flat model with linked selection and vertical scroll; painted hierarchy — chevron hit-rects (`FlatPathDelegate`), prefix path `#707070`, rule `#c8c8c8`, stripe `rgba(0,0,0,22)`, conflict tint, stale orange `#EA580C`; fixed `ROW_HEIGHT` from `UniformRowDelegate.sizeHint` (the source explicitly warns that text-measuring there costs seconds); checkbox/icon alignment in `ActionColumnDelegate`; per-action colours from `action_colours.py` on the Breeze palette; all 720 lines of procedural icons; keyboard behaviour (F5 compare, Space stash, Enter-to-compare, Ctrl+click invert action bar, Enter/Shift+Enter/Ctrl+G/Ctrl+Shift+G search stepping, collapse keys); per-pane context menus whose entries depend on whether the side is local; tooltips including path, conflict reason and `STALE_HELP_TEXT`; status/journal semantics (every command logged *before* running, raw rsync output in the session file, verification before write); and the deliberate accessibility choice of suppressing focus rectangles/mouse-over on rows. Qt's accessibility tree comes from `data()`/`headerData()` and must expose the same roles and labels.

**Can modernize with little risk [E]:** priority/icon prefetch around the visible range, ~25 ms progress throttling, buffered text metrics, wrapped long paths (already present in `text_elide.py`), HiDPI polish and standard Qt dialogs — all without changing semantics.

**Parity verification [E]:** (a) automated pixel/screenshot diff of `docs/main-window.png`, `settings-dialog.png`, `sync-dialog.png` baselines (regenerate them on the current Breeze/X11 setup first — they date from 13 Nov); (b) QTest widget tests asserting shortcut → action, menu item sets, tooltip strings and delegate paint output; (c) differential model tests on synthetic 526k-item data; (d) a written acceptance checklist covering every bullet above, executed against both builds side-by-side on the same 1.2M-item tree.

---

## Final recommendation

**[E] Stay Python, do not rewrite.** The performance case does not survive measurement: ~90% of the workflow is an external rsync that no port accelerates, the hot actions are already sub-second, and the outliers are fixable in Python. Spend a fraction of the 15–21 person-month rewrite budget on: incremental aggregates for `show_excluded`, canonical key caching, text-extent caching, and timing regression gates in `qpy-rsync-test.sh`. If item counts grow 5–10× or memory becomes a hard limit, revisit with a **narrow C++ extension for the filter/row-map core**, keeping the Python GUI; a full C++ Qt rewrite is only warranted if UI framework independence becomes a strategic requirement unrelated to performance.
