# Debugging

Enable console diagnostics when launching the GUI:

```bash
QPY_RSYNC_DEBUG=1 qpy-rsync 2>&1 | tee qpy-rsync-debug.log
```

The report includes:

- the exact argument vector passed to `QProcess`
- process PID and completion status
- byte counts and `repr()` samples of stdout/stderr
- parser input samples and parsed change/diagnostic counts

The output may contain local paths and remote host names. Review it before sharing. It does not intentionally print passwords or private keys.

For interactive UI timings, set a perf-log path before launching:

```bash
QPY_RSYNC_PERF_LOG=/tmp/qpy-rsync-perf.log qpy-rsync
```

Each timed phase appends one line with an ISO timestamp, a phase name and the
elapsed milliseconds, for example:

```
2026-11-26T11:20:00.123-07:00 view.toggle_excluded 18.4ms paths=1
2026-11-26T11:20:00.145-07:00 native.visible_update_incremental 3ms
2026-11-26T11:20:00.148-07:00 native.overview_update 12ms
```

The log covers decision apply/undo/redo, model filter refreshes, overview and
statistics updates, plan rebuilds, show/hide excluded and sorting. When the
variable is unset the logging is completely disabled and the normal path is
unchanged. The file may contain local paths; review it before sharing.

The visible field token is `|qpy-rsync|`. If this exact token appears in a filename, parsing is stopped with an ambiguity error rather than silently producing an incorrect plan.
