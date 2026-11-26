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

For interactive UI timings, enable **Settings > Advanced > Include timing
diagnostics in the session log** (the debug option implies it). No restart or
environment variable is needed: the setting is applied at startup and as soon
as the Settings dialog is accepted. Python and native phase lines are written
to the main session log alongside the journal entries, with an ISO timestamp,
a phase name and elapsed milliseconds, for example:

```
2026-11-26T11:20:00.123-07:00 view.toggle_excluded 18.4ms paths=1
2026-11-26T11:20:00.145-07:00 native.visible_update_incremental 3ms
2026-11-26T11:20:00.148-07:00 native.overview_update 12ms
```

The log covers decision apply/undo/redo, model filter refreshes, overview and
statistics updates, plan rebuilds, show/hide excluded and sorting. Both options
are off by default, so the normal path has no extra work. Optional standalone
capture is still available with `QPY_RSYNC_PERF_LOG=/tmp/qpy-rsync-perf.log`;
that file is only opened when the variable is set. The log may contain local
paths; review it before sharing.

The visible field token is `|qpy-rsync|`. If this exact token appears in a filename, parsing is stopped with an ambiguity error rather than silently producing an incorrect plan.
