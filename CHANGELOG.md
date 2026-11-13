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

## milestone 1.15d execution and validation

- Add write-capable SyncService execution restricted to /tmp/qpy-rsync-smoke.
- Execute verified synchronization plans through temporary private decision filters.
- Add synchronization terminal events for completion, cancellation, and failure.
- Add automatic post-sync comparison after successful execution.
- Add GUI startup options: --dir-pair, --backup, --mode, and --compare.
- Add configurable persistent session logging.
- Add guided synchronization smoke-test framework and reporting.
- Validate Update, Mirror, and New Only synchronization modes with real rsync execution.
- Validate cancellation and failure execution paths.

## milestone 1.15f interface and performance

- Enlarge the shared controls and render the icons from a 64 px canvas so they stay sharp at 24 px.
- Show absolute source and destination paths in the tooltips and the context menu, and add a copy-path entry to every object.
- Keep the journal box directly below its label, let it fill the pane, and show the status messages next to the label.
- Give the action column between the tree panes a fixed width and size the location icons like the buttons in their row.
- Make the command preview resizable and always visible, and let it follow the running operation.
- Store the application settings in `~/.local/state/qpy-rsyncstaterc`, migrate the legacy configuration once, and keep the recent profile inside the state file.
- Write the widget state as base64 text so the state file stays readable for other INI parsers.
- Batch the journal writes, reuse one log handle, and stop writing every rsync line to disk during a comparison.
- Reuse a fresh comparison for the verification instead of starting an identical second dry run, and allow cancelling a modified selection.
- Report a cancelled verification only once and render the rsync specification of every dry run in the journal.
- Keep the tree expansion linear instead of quadratic, so comparisons with thousands of objects stay responsive.
- Show the objects of an inventory immediately and re-evaluate the filtered rows, so the unchanged objects appear without another comparison.
- Stop the running rsync processes when the window closes.

## milestone 1.15g review fixes

- Verify Actions can run again after a successful verification instead of raising an invalid gate transition.
- Store the recent profile and the filter rules as base64 text, so the KDE configuration reader no longer rejects the state file.
- Keep rsync progress and speed lines in the session log and out of the journal, and derive the progress percentage from the files already checked so dry runs show progress.
- Show the progress bar only while an operation runs, and turn the Pause button into Resume while a transfer is suspended.
- Expand every folder after a comparison, so the trees never start half collapsed.
- Use a faded equals icon for folders present on both sides and a tribar for unchanged items, including the inventory button.
- Show folder and file-type icons (picture, document, archive, database, executable, regular) and set changed items in bold.
- Report the number of selected items and their total size in the summary pane and the confirmation dialog.
- Address the comparison content as items everywhere in the interface.
- Add a menu bar with F1 to F11 shortcuts, an About dialog and a profile folder in `$XDG_CONFIG_HOME/qpy-rsync/profiles`.
- Add Debian packaging in `debian/`.

## milestone 1.15h review fixes

- The folder expansion after a comparison follows a setting (all, first level, none) in the new Settings dialog, reachable from Edit and from a gear button next to the filter field.
- Folders that hold changes are bold and carry an accent dot on their equals icon, also while they are collapsed.
- File-type icons only appear on the side where the item exists.
- The tree header calls its rows items and the inventory button shows unchanged items.
- The overview has a Share column header and room for three-digit percentages.
- Button tooltips name the shortcut of the matching menu action.

## milestone 1.15h follow-up

- The summary of the proposed synchronization moved from the status line into the overview pane.
- A Menu button mirrors the application menu, for desktops whose global menu does not reach Qt applications.
- Unchanged items use a checkmark, faded in the trees, so it differs from the active checkboxes and frees the tribar for the menu button.
- Icons of rows without a checkbox line up with the icons of the selectable rows.

## milestone 1.15h verification and help

- The actions summary is written to the journal whenever the selection changes, and a successful verification adds its own summary line with the selected new, updated, metadata, replaced and deleted items plus the item count and size. The overview pane no longer carries summary text.
- A bold Total root row in the overview tree aggregates every item the overview displays and its size, so it follows the action filters.
- Source and Destination use the `folder-open-symbolic` and `folder-add-symbolic` system icons (with color and style fallbacks), so they follow the icon theme and scale cleanly.
- Help -> How-To (F1) opens a scrollable explanation of the workflow, the actions and the verification step; About no longer takes a shortcut.
- The Synchronize tooltip explains the confirmation dialog and the dependency on Verify Actions.
- The synchronization dialog no longer requires an extra acknowledgement checkbox; the reviewed dialog itself is the confirmation. Its fingerprint moved into the header, the explanatory paragraph is bold text instead of a text box, and the statistics are a two-column table.

## milestone 1.15i overview and large comparisons

- The overview tree separates the share bar, the percentage, the folder hierarchy, the item count and the size into their own columns, so deep indentation cannot cut a percentage. Overview and comparison headers are resizable.
- Turning Inventory on for an existing comparison starts the inventory immediately.
- Inventory reports the number of objects listed for the Source, the Destination and the matching phase; the progress bar runs while it works and the journal reports the result.
- Adding a large unchanged set shows a wait cursor and a population message instead of appearing frozen.
- Unchanged-item tooltips no longer end with the raw `=:` itemized code.
- Settings gained an auto-expand limit (default 256 items per folder). Folders above the limit stay collapsed with an amber marker and a tooltip explaining why; opening one by hand clears its marker.

## milestone 1.15j profile and command review

- The synchronization dialog shows the full rsync command in a read-only monospaced box; the temporary decision-filter path is shown as a placeholder.
- Loading a profile with SSH endpoints now restores the complete `[user@]host:path` location instead of only the remote path.
- The Save and Load profile buttons swapped places, so Load comes first like the File menu.

## milestone 1.15k command wrapping and expansion speed

- The command box in the synchronization dialog wraps long options and scrolls vertically.
- The auto-expand limit measures each directory. Branches without an oversized folder open with Qt's native recursive expansion, while every oversized folder stays collapsed and marked, at any depth.

## milestone 1.15l tree fonts

- Changed items use the normal font again; unchanged items are drawn in italic.

## milestone 1.15m overview columns and directory item counts

- The overview combines the share bar and its percentage in one column.
- The comparison trees gain an Items column on each side, reporting all objects below a folder, including nested folders.
- The auto-expand limit applies per directory again, and every directory above the limit is marked at any depth, not only the top level. Branches without an oversized directory expand natively in one pass.

## milestone 1.15n limited-folder finder

- The comparison controls gained a checkable button, left of Unchanged, that filters the trees to the folders left collapsed by the auto-expand limit and opens their ancestors. Expanding the last marked folder restores the full tree automatically.

## milestone 1.15o limited-folder finder restore

- The overview's first header is called Item.
- Turning the limited-folder finder off restores the expansion state that was active before it was turned on. Folders expanded or collapsed by hand while the finder was open are kept, so it no longer leaves the whole tree expanded.

## milestone 1.15p saved header compatibility

- Saved header states carry a column-layout version. A state from an older layout is ignored, and pane column visibility is re-applied after every restore, so stale states cannot reveal duplicate Actions or other panes' columns.
- The legacy `~/.config/qpy-rsync/qpy-rsync.conf` settings file is deleted after it has been migrated, leaving profiles in `~/.config/qpy-rsync/profiles` and runtime state in `~/.local/state/qpy-rsyncstaterc`.

## milestone 1.15q compact compare toolbar

- The last visible column of each comparison pane stretches to the pane edge, so no empty column appears after Modified.
- Secondary toolbar actions use compact icon buttons with tooltips and menu shortcuts. The action-filter checkboxes are smaller. The window can now shrink to 1280 px and has a minimum width of about 966 px in the default theme.

## milestone 1.15r theme icons and name-column width

- Compare, Verify Actions and Synchronize use theme icons (`kr_comparedirs`, `answer`, `media-playback-start-symbolic`); Swap uses `swap-panels-symbolic` and the Source icon uses `inode-directory-symbolic`.
- All toolbar icon buttons use the common 40 px control size.
- The Item column in each compare tree absorbs the extra pane width; Items, Size and Modified keep their widths.

## milestone 1.15s verification progress cleanup

- The progress pane now leaves “Verifying selected actions...” when verification finishes, fails or is cancelled, and reports the final verification state instead.

## milestone 1.15t real decision-filter path

- The synchronization dialog creates the private decision filter before it opens and shows its real path in the command preview. The same file is used by the synchronization and removed when it finishes, fails or is cancelled.

## milestone 1.15u resizable command preview

- The rsync command box in the synchronization dialog now grows and shrinks with the dialog instead of keeping a fixed height.

## milestone 1.15v decision rule preview

- The synchronization dialog shows the generated decision-filter rules in a read-only, wrapping, resizable text box next to the command preview.

## milestone 1.15w sync dialog alignment and preview splitter

- Source and Destination are laid out in an explicit two-column grid, so their labels and values always align.
- The command and decision-rule boxes sit in a draggable vertical splitter; both wrap and resize with the dialog or with the splitter handle.
- The statistics table height includes a small guard band, so its content no longer scrolls by a few pixels without a scrollbar.

## milestone 1.15x static summary table

- The synchronization summary table ignores wheel and scroll requests, so hovering over it can no longer shift its contents by a few pixels.

## milestone 1.15y backup settings commit

- Backup settings are read directly from the fields when a profile is built, loaded profiles initialize the backup state, and verification/synchronization commit pending edits first. A backup directory typed without pressing Enter is no longer ignored.

## milestone 1.15z decision-rules label

- The Decision rules box names the temporary filter filename in its label, with the full path in the label and box tooltips.

## milestone 1.15aa filter indicator

- The icon-only Filters button shows a cyan badge when at least one rule is enabled and an amber badge when the comparison is stale after a rule change.

## milestone 1.15ab external open buttons

- Source, Destination and Backup gained folder buttons, and Log gained a file button. They open the location with Qt's `QDesktopServices`, falling back to `xdg-open`, and report remote or missing paths in the status line.

## milestone 1.15ac missing location warnings

- Opening a missing directory now shows a warning dialog instead of failing silently.
- Compare and inventory refuse to start when a local Source or Destination is missing or is not a directory, and explain the problem in a dialog, the status field and the journal.

## milestone 1.15ad status bar restored

- Status messages appear in a new window status bar as well as the compact State field and the journal. Long messages are clipped in the bar but fully available in its tooltip and in the journal.

## milestone 1.15ae warning-only status bar

- The status bar shows only warnings and errors; ordinary and success messages stay in the State field and journal.
- Missing remembered Source and Destination paths are reported at startup, opening a missing log file warns instead of silently creating it, and a failed external-open attempt reports an error.

## milestone 1.15af journal formatting

- The State field moved from the Journal header to the window status bar.
- Journal lines carry a short `HH:MM` timestamp. Application text uses the readable theme text colour, rsync output is light grey, warnings are cyan, errors red and successes green.

## milestone 1.15ag state bar and journal noise

- The status bar shows only operation states: `Enter locations to compare`, `Ready for compare`, comparison, verification and synchronization states.
- Warnings and errors no longer replace the state; they appear only in the journal, where the colour conveys severity.
- Duplicate backup warnings are collapsed, and journal lines no longer carry the redundant `STATUS` and `Warning:`/`Error:` prefixes.

## milestone 1.15ah remote diff staging

- The verification state now reads “Selected actions verified.” without the extra note about files.
- Diffing a change with one remote endpoint stages that file locally with rsync and opens the normal local diff tool. Staging directories are removed when the app closes.

## milestone 1.15ai diff staging feedback

- Opening a remote file in the diff tool now logs the staging rsync command and its output, sets a "Preparing diff..." state, shows an indeterminate progress bar and uses a wait cursor until staging completes.

## milestone 1.15aj huge inventory expansion guard

- Comparisons above 20,000 items no longer expand automatically, even when each folder is below the per-folder limit. Top-level folders are marked, the journal reports the safety limit, and folders can be opened manually. This keeps adding tens of thousands of unchanged items responsive.
- Folder aggregate refreshes and large marker updates now use a single layout change instead of thousands of dataChanged signals.
