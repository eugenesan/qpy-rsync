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

The visible field token is `|qpy-rsync|`. If this exact token appears in a filename, parsing is stopped with an ambiguity error rather than silently producing an incorrect plan.
