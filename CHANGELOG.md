# Changelog

## 0.1.0.dev0

- Bootstrap the `qpy-rsync` repository.
- Add typed profile and endpoint models.
- Add safe rsync command generation using argument vectors.
- Add initial profile validation and JSON serialization.
- Add a command-preview CLI, tests, and a PySide6 application shell.

- Add Git repository and archive-delivery policy.

## milestone 1

- Add asynchronous `QProcess` execution with cancellation support.
- Add strict parsing of controlled rsync itemized output.
- Add normalized change and object-kind models.
- Add local comparison service.
- Add a sortable, filterable `QAbstractTableModel` comparison UI.
- Add local path selectors, command/log display, status handling, and parser fixtures.

## milestone 1.1

- Fix completion handling across PySide6 versions by comparing `QProcess.ExitStatus` directly instead of converting it with `int()`.
- Forward stderr and process errors through dynamically assigned service callbacks.
- Distinguish process startup from running state and improve failed-start diagnostics.

## milestone 1.2

- Replace the invisible U+001F field separator with the visible `|qpy-rsync|` token.
- Reject ambiguous records when the token occurs in a filename.
- Add environment-controlled console diagnostics for process arguments, raw stdout/stderr samples, completion state, and parser counts.

## milestone 1.3

- Make compare inventory destination-only objects with a dry-run-only `--delete-during` flag.
- Label those records as `destination_only` when profile deletion is disabled.
- Keep actual sync command generation unchanged and non-deleting by default.
- Confirm the final comparison UI direction: a two-pane hierarchical tree inspired by Meld and FreeFileSync; the milestone 1 flat table remains temporary scaffolding.

## milestone 1.4

- Replace the flat comparison table with synchronized source, action, and destination tree panes.
- Build an expandable hierarchy from relative paths and align one-sided objects with empty peers.
- Suppress rsync's synthetic zero size and Unix epoch timestamp on deletion inventory records.
- Infer file/directory type for destination-only records from rsync's trailing slash convention.
- Expand `~` in local endpoint paths without invoking a shell.
