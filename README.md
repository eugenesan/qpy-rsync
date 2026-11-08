# qpy-rsync

`qpy-rsync` is a Linux-focused PySide6 frontend for `rsync`. It uses rsync dry-runs as the source of truth, presents planned changes visually, and will validate user selections before executing a one-way synchronization.

## Current state

Milestones 1 through 1.11 provide a read-only comparison workflow with:

- local and rsync-over-SSH endpoints
- asynchronous rsync dry-run execution and controlled output parsing
- synchronized hierarchical source, action, and destination panes
- destination-only inventory without enabling destructive synchronization
- graphical OpenSSH askpass integration
- optional system-Python or `.venv` development workflows

Synchronization execution and per-object decisions are not implemented yet.

## Requirements

- Python 3.11 or newer
- rsync 3.x
- OpenSSH client for remote profiles
- PySide6 6.7 or newer for the GUI

## Run from a source checkout

A virtual environment is optional. The repository provides system-Python
runners that resolve the checkout location automatically and can be invoked
from any working directory.

Run the application with Ubuntu's system Python and PySide6:

```bash
./qpy-rsync.sh
```

Enable console diagnostics explicitly when needed:

```bash
QPY_RSYNC_DEBUG=1 ./qpy-rsync.sh 2>&1 | tee qpy-rsync-debug.log
```

Run the complete test and source-validation workflow without `.venv`:

```bash
./qpy-rsync-test.sh -q
```

Arguments are forwarded to pytest, so focused test runs work as expected:

```bash
./qpy-rsync-test.sh tests/unit/test_command.py -vv
```

After pytest succeeds, `qpy-rsync-test.sh` also runs Python bytecode
compilation and `git diff --check`.

Both runners use `/usr/bin/python3` by default. Override it when testing another
system interpreter:

```bash
QPY_RSYNC_SYSTEM_PYTHON=/usr/bin/python3.13 ./qpy-rsync-test.sh -q
```

The equivalent direct application command is:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 -m qpy_rsync.app
```

For an isolated development environment instead:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
qpy-rsync
```

See [`docs/installation.md`](docs/installation.md) for Ubuntu runtime and
development packages, system-Python testing, SSH prerequisites, and debugging.
See [`docs/roadmap.md`](docs/roadmap.md) for upcoming milestones and
[`docs/diff-tool-integration.md`](docs/diff-tool-integration.md) for the
external diff-tool design.

## Safety status

This is pre-alpha software. Destructive synchronization and per-object execution are not implemented yet.

## milestone 1 local comparison

The GUI now performs asynchronous local `rsync --dry-run` comparisons and displays normalized changes in a sortable, path-filterable table. It remains read-only: no synchronization action is exposed. See `docs/milestone-1-smoke-test.md`.

## External diff tool

For local-to-local comparisons, right-click or double-click a changed regular
file to open it in an external diff tool. qpy-rsync honors Git's
`diff.guitool`, `diff.tool`, and `difftool.<tool>.path` settings, then looks for
Meld, KDiff3, Kompare, or Vimdiff. Remote-file staging is not implemented yet.

## Comparison-tree filtering and saved state

The comparison view supports case-insensitive filename filtering and shell-style
globs:

- `guide` matches names containing `guide`.
- `*.py` matches Python filenames.
- `file?.txt` uses `?` for one character.
- `[0-9]*` matches names beginning with a digit.
- `*` shows all changed objects.
- `.` matches names containing a literal period.
- `docs/` matches the `docs` directory and retains its complete subtree.

Matching files remain visible with their ancestor directories. Use **Expand
All** and **Collapse All** to control all three synchronized panes.

qpy-rsync remembers the main-window geometry, comparison-pane ratios, column
layout, and the last successfully used source and destination pair. Press
**Enter** in the destination field to start comparison when both endpoints are
present.
