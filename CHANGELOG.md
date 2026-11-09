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

## milestone 1.5

- Normalize UI directory endpoints to trailing-slash content semantics, preventing rsync from nesting the source directory basename under the destination.
- Parse local and rsync-over-SSH endpoint syntax in both location fields.
- Add inline SSH syntax instructions, examples, validation, and `~/.ssh/config` alias guidance.

## milestone 1.6

- Force OpenSSH authentication through `SSH_ASKPASS_REQUIRE=force` for remote profiles.
- Discover `ksshaskpass` and common GNOME/X11 askpass helpers, honoring an explicit `SSH_ASKPASS` first.
- Close the rsync process write channel so SSH cannot hang waiting on unreadable standard input.
- Fail before launching rsync with an actionable message if no graphical askpass helper is available.

## milestone 1.7

- Stop forcing the ASCII `C` locale into rsync/SSH, which broke Qt-based askpass helpers expecting UTF-8.
- Detect Wayland sessions and force Qt askpass helpers to use the `wayland` platform instead of attempting `xcb` without `DISPLAY`.
- Preserve an explicitly configured `QT_QPA_PLATFORM`.
- Reject headless password-authentication attempts before launching rsync with an actionable error.

## milestone 1.8

- Explicitly forward `DISPLAY`, `XAUTHORITY`, D-Bus, and desktop session variables to rsync/SSH for graphical askpass.
- Include the selected display endpoint in debug diagnostics.
- Select `xcb` only when an explicit X11 `DISPLAY` is forwarded, and select Wayland only for a Wayland-only session.

## milestone 1.9

- Sanitize the environment inherited by external rsync, ssh, and SSH askpass processes.
- Remove Python and bundled Qt runtime paths that can interfere with system applications: QT_PLUGIN_PATH, QT_QPA_PLATFORM_PLUGIN_PATH, QML2_IMPORT_PATH, QML_IMPORT_PATH, LD_LIBRARY_PATH, PYTHONHOME, and PYTHONPATH.
- Preserve desktop session, locale, SSH agent, and X11/Wayland variables required by graphical askpass helpers.
- Stop forcing QT_QPA_PLATFORM, allowing system helpers such as ksshaskpass to select their own system Qt platform plugin.
- Add tests covering child-process environment sanitization and update SSH askpass tests for the new platform-selection behavior.

## milestone 1.10

- Run remote rsync operations through `setsid --wait`.
- Configure rsync's remote shell as `env DISPLAY=<display> ssh` so graphical OpenSSH askpass can reach the active X11 display.
- Keep local rsync operations direct and preserve external OpenSSH credential handling.
- Add tests for remote compare and sync process construction and display propagation.

## milestone 1.11

- Document Ubuntu runtime and development packages for system-Python operation.
- Make `.venv` explicitly optional and document `qpy-rsync.sh` and direct `PYTHONPATH` launch workflows.
- Document SSH prerequisites, validation commands, and optional Ruff usage.
- Add the external diff-tool integration design and the revised milestone roadmap.
- Add source runner with a system-Python launcher and add qpy-rsync-test.sh for system-Python tests and validation.

## milestone 1.12

- Add **Open in Diff Tool** to the comparison-tree context menu and double-click handling.
- Resolve Meld, KDiff3, Kompare, or Vimdiff using Git-compatible `diff.guitool`, `diff.tool`, and `difftool.<tool>.path` precedence.
- Launch local-to-local changed regular files in a detached external diff tool without shell evaluation.
- Reject one-sided objects, non-regular files, and SSH endpoints with actionable messages; remote staging remains planned.
- Add unit tests for tool resolution and diff-request validation.

## milestone 1.13

- Restore hierarchical, case-insensitive filename filtering while retaining ancestor directories.
- Add shell-style glob filters, including `*`, `?`, and bracket expressions such as `[0-9]*`.
- Add trailing-slash directory filtering, such as `docs/`, that retains the matched directory's complete subtree.
- Add synchronized **Expand All** and **Collapse All** controls and ensure deep branches expand after model resets.
- Correct destination-pane tree rendering and improve source/destination column resizing.
- Persist main-window geometry, comparison-pane ratios, and header state with `QSettings`.
- Remember the last successfully used source and destination pair and start comparison when Enter is pressed in the destination field.
- Add regression tests for glob matching, punctuation filters, clearing filters, numeric names, and directory-subtree display.

## milestone 1.14

- Add explicit include, exclude, and inherited decisions for changed objects.
- Add checkboxes to the center action column while keeping comparison non-destructive.
- Make real and synthetic directory checkboxes control their complete subtrees through inherited decisions.
- Allow child decisions to override an excluded parent and allow excluded files and directories to be checked again.
- Preserve decisions across recompare when path, action, and object kind remain stable.
- Discard stale decisions when an object's identity changes or a synthetic directory subtree disappears.
- Track included, excluded, and included-destructive counts for the future execution plan.
- Stabilize filtering after proxy resets so clearing punctuation and glob filters restores and expands the complete tree.
- Add tests for inheritance, child overrides, stale decisions, summaries, non-selectable records, tree checkboxes, and directory subtrees.

## milestone 1.15a

- Add persistent ordered rsync include, exclude, and advanced filter rules.
- Generate classic `--include` and `--exclude` options while retaining native `--filter` support.
- Preserve exact mixed-rule order and omit disabled rules without deleting them.
- Add rule creation, editing, duplication, removal, reordering, enable/disable, comments, import, and export.
- Persist ad hoc filters, rule types, enabled states, comments, and ordering across restarts.
- Retain the previous comparison after filter changes, mark it stale, and lock per-object decisions until comparison succeeds again.
- Add tests for command-vector ordering, profile serialization, rule validation, editor models, and settings serialization.

## milestone 1.15b

- Replace selective backup modes with one optional user-managed backup directory.
- Enable backups only when the directory field is non-empty and always pair `--backup` with `--backup-dir`.
- Migrate legacy backup-mode profiles to the unified altered-object backup policy.
- Reject filesystem root, endpoint syntax, control characters, and source/destination equality.
- Warn for home-directory, relative, nested, containing, unprotected, and in-place configurations.
- Detect nested backup trees and inject explicit protect and exclude rules before user filters.
- Inspect local backup directories as missing, empty, non-empty, or unknown; leave remote status unchecked.
- Add persistent backup controls, nested-protection override, status reporting, stale-state locking, and live command preview.
- Add tests for migration, path resolution, validation, command ordering, inspection, settings persistence, and local home expansion.

## milestone 1.15c

- Add immutable execution plans containing profile fingerprints, comparison identities, effective actions, and confirmation-ready counts.
- Generate private mode-`0600` decision-filter files and remove them after verification.
- Run a second dry-run validation and report missing or unexpected actions before confirmation.
- Separate unchecked actions from Destination-only objects retained by mode defaults.
- Add a wide-screen Source/Action/Destination workflow, compact Filter/Find controls, endpoint swapping, stale-tree presentation, severity-colored messages, and command diagnostics.
- Add mandatory offscreen Qt tests and native-crash diagnostics to `qpy-rsync-test.sh`.
- Harden proxy selection resets and context-menu proxy-to-source mapping after reproducing and fixing two native Qt crashes.

## milestone 1.15d planning and confirmation

- Add Update, Mirror, and New Only one-way synchronization modes.
- Generate Mirror deletion timing and New Only `--ignore-existing` command behavior.
- Migrate legacy delete profiles to Mirror semantics.
- Allow Destination-only rows to default to Keep in Update/New Only and to be checked explicitly for deletion.
- Add decision reset operations for one row, a subtree, and the full tree.
- Add an execution-gate state machine covering comparison, verification, confirmation, execution, completion, failure, and cancellation states.
- Add a final confirmation dialog with operation counts, destructive warnings, backup state, nested protection, verification fingerprint, and explicit acknowledgment.
- Keep real synchronization disabled pending the write-capable synchronization service.
- Add deterministic setup and result-collection scripts for disposable synchronization smoke tests.
