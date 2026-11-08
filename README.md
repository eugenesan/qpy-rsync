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

A virtual environment is optional. With Ubuntu's system Python and PySide6:

```bash
./qpy-rsync.sh
```

The equivalent direct command is:

```bash
PYTHONPATH="$PWD/src" /usr/bin/python3 -m qpy_rsync.app
```

For an isolated development environment:

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
