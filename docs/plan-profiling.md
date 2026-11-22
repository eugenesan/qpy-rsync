# Profiling the plan build

The plan-build path is instrumented with low-overhead timing probes. They are
off by default; enabling them adds a few `perf_counter()` calls per phase.

## Enable

```sh
QPY_RSYNC_PROFILE=1 ./qpy-rsync.sh
```

To keep a separate capture on the big tree:

```sh
DISPLAY=:50 XDG_CURRENT_DESKTOP=KDE QPY_RSYNC_PROFILE=1 \
  ./qpy-rsync.sh 2> /tmp/qpy-plan-profile.log
```

`QPY_RSYNC_TIMING=1` or `QPY_RSYNC_DEBUG=1` also enables the probes; the
`PROFILE` variable is the intended one for this exercise. Each timing line is
written both to stderr and to the current profile's session log in
`$XDG_CACHE_HOME/qpy-rsync/app-<profile>.log`, so captures from several
comparisons are kept with their own logs.

Lines look like:

```
[qpy-rsync timing] 2026-11-22T11:52:14.277-07:00 plan.loop ms=9.3 changes=5000
```

Local time, event name, elapsed milliseconds, and the item count where useful.

## Probe map

Compare setup and handoff:

| event | covers |
|---|---|
| `ui.model_set_changes` | Python model feed (`changes`, `skip_view`, `skip_reconcile`) |
| `view.set_changes` | existing whole-view signal cascade |
| `ui.native_handoff` | Python → native dataset transfer when hybrid is on |
| `model.reconcile` | `ChangeDecisions.reconcile` — defaults, conflicts, stale decisions |
| `model.conflicts` | conflict refresh |
| `model.build_rows` / `model.apply_filters` | Python-only view work (off in hybrid) |
| `ui.overview_update` | overview refresh |

Plan rebuild:

| event | covers |
|---|---|
| `ui.plan_rebuild` | whole `_rebuild_plan_summary` |
| `plan.build` | `build_execution_plan` total |
| `plan.destination_index` | destination size index construction |
| `plan.modified_count` | decision override count |
| `plan.loop` | per-change walk that creates `PlanItem`s |
| `plan.deleted_sizes` | deleted-directory size aggregation |
| `plan.digest` | fingerprint SHA-256 over all plan items |
| `plan.post_index` | sort + `_plan_paths` / `_plan_items` / `_plan_changes` maps |
| `plan.state_snapshot` | excluded paths, explicit decisions, executable hint |
| `plan.freshness_check` | `check_plan_freshness` before sync confirmation |
| `ui.estimated_summary` | stale-state estimate (`plan.estimated_excluded`, `plan.estimated_modified`) |
| `verify.plan_rebuild` | plan rebuild during Verify Decisions |

## What to collect

For each big-tree comparison, record:

- total items and changed items;
- hybrid on vs off;
- `ui.model_set_changes`, `model.reconcile`, `plan.build` and its sub-probes,
  `plan.post_index`, `ui.overview_update`;
- any `ui.estimated_summary` / `plan.freshness_check` lines that appear after
  decision edits.

The sub-probes of `plan.build` tell us whether the cost is in the per-change
loop, `modified_count` (which walks ancestors per explicit decision), the
digest, or deleted-size handling. That decides whether a Python-side fix is
enough or whether a native summary kernel is worth considering.
