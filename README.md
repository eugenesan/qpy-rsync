# qpy-rsync

`qpy-rsync` is a Linux-focused PySide6 frontend for `rsync`. It uses rsync dry-runs as the source of truth, presents planned changes visually, and will validate user selections before executing a one-way synchronization.

## Current state

Milestone 0 bootstrap. The repository currently includes:

- typed endpoint and profile models
- rsync argument-vector command builder
- option compatibility validation
- JSON profile serialization
- CLI command-preview harness
- unit tests
- initial PySide6 application shell

No synchronization is executed by the CLI preview command.

## Requirements

- Python 3.11 or newer
- rsync 3.x
- OpenSSH client for remote profiles
- PySide6 6.7 or newer for the GUI

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
qpy-rsync-cli preview examples/profile.json
qpy-rsync
```

## Safety status

This is pre-alpha software. Destructive synchronization and per-object execution are not implemented yet.

## milestone 1 local comparison

The GUI now performs asynchronous local `rsync --dry-run` comparisons and displays normalized changes in a sortable, path-filterable table. It remains read-only: no synchronization action is exposed. See `docs/milestone-1-smoke-test.md`.
