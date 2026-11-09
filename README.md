# qpy-rsync

`qpy-rsync` is a Linux-focused PySide6 frontend for `rsync`. It uses rsync dry-runs as the source of truth, presents planned changes visually, and will validate user selections before executing a one-way synchronization.

## Current state

Milestones 1 through 1.15a provide a read-only comparison and planning workflow with:

- local and rsync-over-SSH endpoints
- asynchronous rsync dry-run execution and controlled output parsing
- synchronized hierarchical source, action, and destination panes
- destination-only inventory without enabling destructive synchronization
- graphical OpenSSH askpass integration
- optional system-Python or `.venv` development workflows

Per-object decisions and persistent ordered filters are implemented. Synchronization execution is not implemented yet.

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

## Per-object decisions

The center **Action** pane contains a checkbox for every selectable changed
object. Checked objects are included in the future synchronization plan;
unchecked objects are excluded. These controls do not execute `rsync`.

Directories, including synthetic parent directories created for the tree,
control their complete subtrees. A child can override an excluded parent by
being checked explicitly, and checking the directory again includes the
subtree. Message and no-change records are not selectable.

Decisions survive a recompare only while the same path retains the same action
and object kind. Stale decisions are discarded when that identity changes.

## Persistent rsync filters

Use **Filters...** to maintain one ordered list of persistent rules. Rules are
saved across restarts and are applied to both comparison and future execution.
The first matching rsync rule wins.

The editor supports three rule types:

- **Include** generates `--include=PATTERN`.
- **Exclude** generates `--exclude=PATTERN`.
- **Advanced** generates `--filter RULE` for native rsync filter syntax.

Include and exclude are the recommended interface for ordinary rules. Advanced
rules support native rsync features such as protect/risk rules and merge files.
Classic include/exclude options and advanced filter rules share the same ordered
rsync rule list.

Rsync must be allowed to traverse parent directories before it can match an
included descendant. For example, to include only the root `.git/HEAD` entry:

```text
Include  /.git/
Include  /.git/HEAD
Exclude  /.git/***
```

Rules can be enabled or disabled without removal. Disabled rules retain their
position, type, pattern, and comment but are omitted from the rsync argument
vector. Import reads native rsync filter-file lines as Advanced rules. Export
writes all enabled rules in native filter-file syntax.

Changing rules keeps the previous comparison visible but marks it **STALE**.
Per-object decision checkboxes are locked until a new comparison succeeds;
browsing, expansion, visual path filtering, and diff-tool inspection remain
available. A checkbox decision cannot re-include an item excluded by persistent
filters because rsync did not return that item in the comparison.
