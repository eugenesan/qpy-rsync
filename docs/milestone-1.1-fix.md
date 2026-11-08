# milestone 1.1 completion fix

The initial milestone 1 runner converted `QProcess.ExitStatus` with `int()`. PySide6 enum conversion behavior varies by release, and a `TypeError` in the finished callback leaves the GUI displaying `Comparing...` after rsync has exited.

The runner now compares the enum directly with `QProcess.ExitStatus.CrashExit`, drains final stdout/stderr, and always forwards the result. Error and stderr handlers are also dynamically forwarded so callbacks assigned by the main window after service construction take effect.

Retest with the same two directories. The status should change to `Comparison complete`, and the table should populate after rsync exits.
