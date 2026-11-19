# Changelog

## Unreleased

- "Verify Actions" is now "Verify Decisions", matching the decisions it
  verifies; the verification log and status use the same wording.
- Search now scans the whole comparison, not just the rows currently on
  screen: folded folders no longer hide matches, and jumping to a match
  expands its ancestors. Fixed the row-index mapping used by Find Next.
- The default metadata-only colour is violet, so its icons no longer blend
  with the inactive selection colour in the opposite pane.
- Search follows the Find/Filter rules exactly: `dir/` matches only the
  folder named `dir`, `dir/a` is an unanchored path match, globs such as
  `*dir/*.txt` work, and a plain name matches only that item's name.
- The synchronization dialog shows Backup and Nested protection beside Source
  and Destination instead of in the statistics table. Long paths are elided
  to one line with the full value in a tooltip, so the table no longer grows
  into the warning below it.
- The stash is gone. Excluding an item is now the same EXCLUDE decision as
  unchecking its checkbox: Space, the context menu and the overview all use
  it, the filter bar says "Show excluded items" / "Reset All Exclusions", and
  the crossed-eye marker in the action column was removed. The execution plan
  takes exclusions only from the decisions.
- Fixed stashing a directory in the comparison view: the directory row
  disappeared but all of its children, including destination removals, stayed
  in the list. The incremental refresh now marks every descendant as excluded.
- The Overview updates only the folders affected by a decision instead of
  rebuilding the whole tree. Single-item decisions are roughly ten times
  faster on large comparisons.
- The result filter and the row delegates use precomputed row arrays and fixed
  row heights, cutting a full filter refresh on 1.2M items to about 1.0–1.3s.
- The filtered rows, directory totals and overview totals are now collected in
  a single pass. The overview keeps its folder tree and only updates counts and
  visibility, so a global filter change no longer rebuilds 30k folder nodes.
  Decision effects and per-folder totals are cached and updated incrementally
  as well. On a 520k-item comparison this roughly halves the filter time and
  removes most of the overview cost; single-item decisions stay around 0.2–0.4s.
- Exclude/show toggles no longer copy the full change list through a Qt signal,
  and the excluded-state update is merged into the single row rebuild pass.
- The Overview applies only changed folder counts and propagates total deltas
  up the tree, so a single decision updates in ~20 ms on a 31k-folder tree
  instead of rebuilding every folder total.
- Search now follows the Find/Filter rules: a bare name matches only the
  item's own name, a pattern with a slash matches the relative path, globs
  work in both forms, and a trailing slash restricts the search to folders.
  Searching for `.git` no longer matches every file below that directory.
- Search is now indexed: folded names and paths are cached, the match list is
  built once per search text, and Enter/Shift+Enter step through it in O(1).
  Typing searches after a short debounce and a counter shows the match number.

## 0.3.3

- Profiles now store filter rules as a single editable list of text lines;
  `tools/convert-profiles.py` converts older profiles. The Manage profiles
  menu can also open the profiles directory.
- Added three compare layouts (Normal, Compare only, Compare with overview)
  with a toolbar button, a View menu and Ctrl+Tab / Ctrl+Shift+Tab shortcuts.
- The profile editor exposes --checksum, --partial-dir and --inplace, with
  rsync option tooltips on every setting that adds one.
- Deleted files and directories now show their real destination sizes, and
  the Overview pane reports the total deleted size. Directory rows show only
  the sizes of affected items inside them.
- Long names are elided in the panes, context menus and tooltips; added
  Copy Filename and Copy Relative Path actions. The overview is wider and
  the command preview no longer squeezes the journal.
- Fixed a native crash in the inventory worker by passing only a token across
  the Qt thread boundary; the runner now enables Python faulthandler.

## 0.3.2

- Added three compare layouts — Normal, Compare only and Compare with overview —
  with a toolbar button, a View menu and Ctrl+Tab / Ctrl+Shift+Tab shortcuts.
  Each layout keeps its own splitter sizes.
- The profile editor now exposes --checksum, --partial-dir=.rsync-partial and
  --inplace, and every setting that adds an rsync option shows that option and
  a brief explanation in its tooltip.
- The filter editor keeps the raw filter text (including comments) in the
  profile, has a line-number gutter, a resizable two-line rule preview and
  reports the first invalid line on close.
- Added optional hidden "Size (bytes)" columns that replace the formatted Size
  column. An action-bar toggle also applies the action filters to reported
  directories, showing filtered directories as faded parents.
- Fixed the line-number gutter painting and stopped long rules from resizing
  the filter dialog.

## 0.3.1

- Fixed the "Exclude via Filter" entries of the item context menu: the
  "by name" option now generates rsync's basename pattern (`name` or `name/`)
  instead of `*/name`, so it also matches items at the transfer root.
- Filter validation and syntax highlighting now cover all advanced rsync
  filter rules, including modifiers such as `-s`, `-p`, `+r` and merge rules.
- A stale comparison stays browsable: lists, context menus, tools and further
  filter additions keep working, while decisions and synchronization remain
  disabled until Compare runs.

## 0.3.0

- Profiles are now managed from a single button with Load, Save, a list of up
  to ten recent profiles, Save As, Edit and Reset. The profile editor holds
  transfer, preservation, backup, conflict-policy and filter settings; filters
  are no longer kept in the application state file.
- The auto-inventory toggle is now part of the profile instead of the global
  application state. Older profiles default to off and are updated on the next
  save.
- Added an application-wide shortcut set: Alt+S/D for the location fields,
  Ctrl+S/D/N for the compare panes, Ctrl+W for the overview, Alt+Enter/Ctrl+T
  for the item context menu, numbered action and tool shortcuts, and Esc to
  leave a location field. The How-To documents them.
- The comparison and synchronization progress bars are determinate, same-size
  content changes are no longer mistaken for metadata-only updates, and
  repeated location edits no longer mark the comparison stale on every key.
- The filter editor gained a Help button; the profile menu marks unsaved
  changes and Save now asks for confirmation before writing.
- The CLI has a version flag and a runner script; packaging installs the
  README and the full changelog.

## 2.0.1

- The filter editor is now a single text editor using rsync filter syntax;
  lines without an operator are treated as exclusions, and commenting or
  uncommenting a line is the only way to enable or disable a rule.
- The editor provides syntax highlighting, validation and a live preview of
  how the current line is interpreted, plus Import, Export, OK and Cancel
  buttons and a Help button with an rsync filter explanation.
- Progress reporting is restored to the dry-run comparison.
- The window title no longer carries the version string.


- The readme describes the application, its usage and its screenshots, and
  points at the installation and the debugging documents.
- The design, the architecture and the specifications live in one document,
  `docs/design.md`.
- The milestones and the plan live in one document, `docs/roadmap.md`.
- The version moves from 0.1.0.dev0 to 0.2.0.
- `dump-content.sh` moves to `tools/`.

## 0.1.0

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

## milestone 1.15ak configurable total expansion limit

- Automatic expansion now stops at 10,000 comparison items by default; the limit is configurable under Settings → Auto-expand comparison up to.
- Showing a large inventory warns before adding it and offers Add Collapsed (default, marked folders, no expansion) or Expand Normally (may freeze), with Cancel.
- The collapsed choice bypasses the previous-expansion restore, so the proxy filter and per-row expansion path shown in the abort log is not entered.

## milestone 1.15al changed-paths expansion

- The large-inventory warning now offers Expand Changed Only, with the number of changed items and the folders that would open. It is the default when that set is within the configured comparison limit.
- Expand Changed Only opens only ancestors of changed items; unchanged-only folders stay collapsed.

## milestone 1.15am flat comparison list

- The comparison can now be listed flat, in the style of FreeFileSync: a flat list of rows where the directory hierarchy is painted instead of modelled. Settings → Comparison list switches between "Tree with expandable folders" and "Flat list (FreeFileSync style)".
- The flat list has nothing to expand, so a comparison with 80,000 items opens in about 0.6 seconds instead of freezing for 17 seconds while every folder is expanded.
- Every directory is a row of its own, so a directory can be pointed at and decided like an item. The decisions are keyed by path, so the sync semantics are unchanged.
- The path filter, the action filter and the unchanged items work the same as in the tree; a test compares both models side by side.

## milestone 1.15an hide and filter items

- The comparison list can hide the selected item or folder with the space bar, the way FreeFileSync does it. A hidden item is not part of the sync; the list only lives in memory, so it is gone after the next comparison.
- The Actions filter bar carries a hidden-items toggle with a count, so what was hidden can be seen and restored. FreeFileSync has no such indication.
- The context menu filters the selected item the way FreeFileSync does, with the rules written as rsync patterns: by extension (`*.jpg`), by name (`*/name`) or by relative path (`/path/name`). A filter added from the menu is an ordinary exclude rule and marks the comparison stale.
- The same hiding and filtering works in the Overview pane.

## milestone 1.15ao the inventory follows the list layout

- The flat list no longer shows the large-inventory warning. It has nothing to expand, so the expansion limits and the tree-only choices ("Add Collapsed", "Expand Changed Only", "Expand Normally") do not apply, and the unchanged items are simply added.
- Settings disables the three expansion settings while the flat list is selected, with a note explaining why.
- Cancelling the warning now resets the progress bar and keeps its own message instead of leaving the bar animating and the "Inventory complete" text behind, and the unchanged toggle returns to its off state.
- The inventory message says "expand folders to view nested items" only for the tree.

## milestone 1.15ap drop the tree-only expansion machinery

- The large-inventory warning is gone. It existed only to avoid freezing the tree while expanding tens of thousands of rows; the flat list adds 80,000 unchanged items in about three seconds and needs no question. A tree above the comparison limit now simply stays collapsed and marks its top-level folders, with a note in the journal.
- The per-folder expansion limit ("Auto-expand folders up to") is removed. Only the comparison-wide limit remains, and only for the tree.
- "Expand Changed Only" and the forcing of an over-limit expansion are removed with the dialog; the marker button still finds the folders the limit left collapsed.

## milestone 1.15aq one comparison view

- The tree is gone from `main`. Keeping two views meant keeping every tree-only workaround alive: the expansion dialog, the per-folder limit, the comparison limit, the Settings dialog and a proxy layer that the flat list never used. The tree implementation is preserved on the `main-tree` branch.
- Removed `comparison_view.py`, `change_tree_model.py`, `change_filter_proxy.py` and the Settings dialog, which held nothing but the two view settings.
- `full_path` and the shared control sizes moved to `paths.py` and `controls.py`.
- The flat view now sizes its unchanged toggle like the other toolbar buttons.

## milestone 1.15ar settings, statistics and list polish

- Settings is back, with a gear button in the toolbar and `Ctrl+,`. Logging and backup configuration moved into its tabs; the toolbar keeps a button that opens each location, and a right-click on it offers "Configure...", which opens the matching tab.
- A completion sound plays after a comparison and after a sync (success or failure). It uses the desktop sound when available and the terminal bell otherwise, and can be turned off in Settings.
- The Overview pane shows the selected amounts like FreeFileSync's statistics panel: the item count and size plus a count per action. Its size column now takes the remaining width.
- The compared folder is a row of its own, named after the location and totalling everything below it; its checkbox decides the whole comparison.
- The list alternates the background per directory group, paints the selection in the item columns and no longer draws the dotted focus rectangle next to the hover highlight.
- The path filter waits for a short pause or Enter before it runs, matches folders typed with a trailing slash and matches relative paths such as `docs/sub`. Filtering 80,000 items takes about 0.1 s.
- Sorting by size, date, count or action orders the whole list like FreeFileSync, and a second click reverses it.
- Removed the unused `change_model.py` and `elided_label.py`.

## milestone 1.15as destination metadata and columns

- A comparison reports the source metadata, so an object that exists only on the destination arrived with a size of 0 B and no date. A short destination listing now fills both in after every comparison that has destination-side items.
- The Items, Size and Modified columns can be switched off from the header context menu; the choice is remembered per pane. A saved header from an older layout can no longer shrink the name column to an unreadable width.

## milestone 1.15at compact layout and local open actions

- The Source and Destination glyphs are gone. A thin arrow above the filter checkboxes shows the comparison direction, and the checkboxes sit at the bottom of the row so the row does not grow.
- The unchanged toggle is a checkbox next to the hidden one, the Browse buttons became folder icons, the backup button uses the backup icon, and a separator now sits between Pause and Filter.
- The Journal and Overview headings and their rows are removed; the panes speak for themselves.
- The compare and overview headers are only as tall as their text, and the overview footer fits on one row.
- Showing the hidden items no longer changes the overview tree or the statistics: the visible set for those still excludes hidden items until one is restored.
- The context menu offers Open File and Open in Directory for items whose side is local.

## 0.2.0

## 1.15au hidden items, direction line and filter semantics

- Showing the hidden items now writes to the journal and the progress line, the way the unchanged items do.
- A row that is hidden carries a crossed-eye marker in the Actions column. The marker is faint on every other row and can be clicked to hide or restore it.
- Each side names its own root folder, so a destination with a different name reads correctly.
- A filter that ends with a slash matches directories only; files no longer match by name in that case, which restores the tree behaviour.
- The direction line above the filter checkboxes reads "Source → Destination" with a larger arrow in the middle.
- The backup button stays enabled so its context menu reaches the backup settings even before a directory is configured.
- The Overview pane starts wider, its Item column absorbs the extra width, and its footer fits on one row.
- Verifying the actions no longer fails because an item is hidden: a hidden item is deliberately outside the sync, so the plan that leaves it out is correct.

## 1.15av table panes instead of tree panes

- The three comparison panes are `QTableView` widgets. The list is flat, so a tree kept per-index tree state for rows that never have children, and that was the dominant cost of loading a large comparison.
- A fixed vertical-header row height replaces `setUniformRowHeights`; the row numbers are hidden and the grid is off, so the panes look the same as before.
- Measured on the real view with three panes: 300,000 items load in 3.4 s instead of 11.2 s and sort in 3.3 s instead of 11.1 s; 1,200,000 items load in 12.4 s instead of 44.5 s, sort in 9.4 s and filter in 2.2 s, using 1.5 GB.

## 1.15aw compact actions, touch marker and quiet terminal

- A directory now comes before its own items and then its subdirectories, so a directory sits next to its contents.
- The stripes alternate row by row, not group by group: a directory and its first item never share a stripe, and no run of items is drawn as one block.
- The crossed-eye marker in the Actions column is watched on the viewport, not the pane, so it responds to a real click. A touchscreen tap is handled as `TouchBegin` because the viewport accepts touch events and receives no synthesized mouse press.
- The marker hit area covers the full height of the row and a little more to the left, which makes it usable with a finger.
- The direction line is a single compact row and the filter checkboxes are 40 px tall, so the locations row is 56 px instead of 77 px.
- The invalid `QSG_RHI_BACKEND=software` is gone: Qt has no software RHI backend, and asking for one falls back to OpenGL. `QT_QUICK_BACKEND=software` is the setting that selects the software Qt Quick adaptation.
- GLX probe warnings are kept out of the terminal; on a remote X server they repeated once per probe even though this is a widgets-only application.

## 1.15ax unhide all and action sorting

- The Actions context menu, including the empty part of the Actions pane, offers "Unhide All (N)".
- The hidden-items toggle has a right-click menu with the same action, and its tooltip points to it.
- Sorting by the Actions column was already intentional: it sorts the whole list by action label and reverses on a second click. A test now covers ascending and descending order.

## 1.15ay stash and restore

- "Hidden items" are now "stashed items". A stashed item is temporarily left out of the sync, kept in memory, and gone after the next comparison; the behavior itself is unchanged.
- The space bar and the context menu say Stash Item, the restore entries say Restore Item and Restore All Stashed, and the toggle is "Show stashed items".
- The stashed toggle shows its count next to the crossed eye, and its tooltip explains the right-click Restore All Stashed action.
- The overview pane uses the same wording for folders.
- The internal names follow the UI: `StashedItems`, `model.stash`, `stash_path`, `restore_path`, `restore_all_stashed`, `STASHED_ROLE`.

## 1.15az collapse and expand

- Every directory row carries a branch marker in the Item columns. Clicking it folds the directory's contents out of the list; clicking it again expands them. Double-click, Left, and Right work like a tree.
- Folding is view-only. Folded items remain in the sync, the totals, the statistics, and the overview; only the list rows are out of the way.
- The row context menu has a Collapse / Expand submenu with the folder action and Collapse All Folders / Expand All Folders. The same global actions are in the Actions menu and in the empty part of the Actions pane.
- A path filter temporarily overrides the folds so a search never loses its matches; clearing the filter restores the folds.
- Selecting a path from the overview or the filter expands its ancestors first.
- Folds live in memory, survive sorting and inventory toggles, and are cleared when a new comparison starts.

## 1.15ba pointer focus on the action filters

- The action filter checkboxes take focus only from the keyboard (`TabFocus`). A pointer click no longer leaves Breeze's focus underline behind, while Tab and Space still reach and toggle the filters.

## 1.15bb the parent folder, colours and filter fixes

- The compared folder is the parent of the tree: it has no branch marker, it sits at the far left, and it uses the folder-root-symbolic icon.
- A created or destination-only item is coloured in the Item column too, not only in the size and the date.
- The action filter bar separates every pair of checkboxes with a line, so it is clear which indicator belongs to which glyph.
- A filter no longer leaves a folder behind without its items: a folder is shown when its name matches, or when it holds an item that matches and is allowed.
- The unchanged items are no longer dropped when an action checkbox is used. The toggle that shows them allows them explicitly.
- The settings dialog has a test module of its own again.

## 1.15bc external tools

- The settings have a Tools page that lists the tools the context menu of a row offers. A tool is a command with placeholders: `%a`, `%f`, `%x`, `%b` and `%d` for the item in the pane that was clicked, `%A`, `%F`, `%X`, `%B` and `%D` for the item in the other pane, `%R`, `%U`, `%V`, `%W` and `%P` for the remote side of the other pane, `%T` for the tool, `%O` for its options and `%%` for a literal percent.
- The command is split into words before the placeholders are filled in, so a path with a space stays one argument. A placeholder without a value leaves nothing behind.
- The diff tool command moved to the same page and uses the same placeholders. An empty field keeps the tool that the system offers.
- Asking for the unchanged items switches the inventory button on, so the second listing that a comparison needs is explained instead of surprising.

## 1.15bd the inverted click on the action bar

- Ctrl+click on a checkbox of the action bar inverts the filter: the clicked action is the only one that is shown, and a second inverted click shows everything but that action.
- The context menu of every checkbox offers the same choice: Show only this, Show everything but this, Show all, and Reset to default, which puts the six action checkboxes back on and the unchanged and stashed toggles back off.
- A plain click still toggles a single action, and the tooltips mention the inverted click.
- The stashed items are shown whenever the "Show stashed items" toggle is on, even when the action filters exclude their action. The inverted click on the stashed toggle therefore shows only the stashed items.

## 1.15be the second inverted click

- The inverted click on a checkbox of the action bar toggles between two states. The first one shows only the clicked action; the second one, and an inverted click on a switch that is off, reverse it and every action comes back.
- The reversal leaves the unchanged and the stashed toggles alone, because they are not part of the action filter.
- The context menu of a checkbox still offers *Show only this*, so the unchanged and the stashed items can be shown on their own.

## 1.15bf the hover, the action colours and the missing side

- The pointer marks the whole row now, in the pane it is in and in the other one. The tooltips and the context menus stay with their own side.
- Every action has a colour that marks its items: green for created, light yellow for updated, cyan for metadata only, orange for replaced, red for deleted and brown for the items that only exist in the destination. The glyph of the action carries the same colour.
- The settings have an "Action colours" page where every colour can be changed and every marking can be switched off.
- An item is only shown on the side where it exists: a deleted item appears in the destination only, and its source size is no longer a confusing zero.
- The file type icons carry the colour of their type, so a picture, a document and an archive are told apart at a glance.
- The toolbar has its separator between the pause button and the filters button again, the log button uses folder-log-symbolic and the settings button settings-configure-symbolic.

## 1.15bg no placeholder on the root row

- The root row of the comparison shows the name of the compared folder, or nothing when there is no folder yet. A dot would look like an item of the comparison.

## 1.15bh the root folder reads as a folder

- The root row now shows its full path instead of a dot when the folder has no
  basename, and the root icon is a folder with a mark instead of the
  folder-root-symbolic glyph, which Breeze draws as a slash.

## 1.15bi the root folder icon

- The root folder icon is painted as a folder with a mark, instead of the
  folder-root-symbolic theme icon, which Breeze draws as a slash.

## 1.15bi the root folder is not an item

- rsync reports the compared folder itself as "." or "./". That is the root of
  the list, not an item inside it, so it is no longer shown as an item.

## 1.15bj resizable item columns

- The Item columns of the comparison panes and the overview pane take all the
  free space by default, but they can now be resized by dragging their edge.
  The column keeps the chosen width until the comparison changes.

## 1.15bk the records stay clean and the terminal stays quiet

- The comparison no longer asks rsync for its progress. Rsync writes the progress to stdout with a carriage return, so it ended up in front of the next record and the parser read a broken itemized code. Such a record was reported as a metadata change instead of the change it was.
- The parser rejects a record whose code is not an rsync itemized code, so a mixed-up line is reported instead of silently changing the action of an item.
- The model is reset when the rows change instead of announcing a layout change. A layout change left the accessibility interface with a stale row count, which produced the "QAccessibleTable::child: Invalid index" warnings.
- The selected row is kept when the model is reset.
- The harmless OpenGL notices of the KDE platform theme ("Cannot create platform OpenGL context" and "fallback to QtQuick software backend") are kept out of the terminal; every other message still comes through.

## 1.15bl the action of an item and the log file

- The action of an item now follows the attributes that rsync reports. A file whose modification time, permissions, owner or group changed is a metadata change, even though rsync marks it with the transfer marker. Only a changed value or a changed size is a content change.
- The right-click menu of the log button has a "Clear Log" entry that empties the log file and keeps the session logging into it.

## 1.15bm the build in the about dialog

- The About dialog reports the commit of the checkout, so it is visible which
  build is on the screen. The application often runs from a copy that is
  synchronized from another machine.

## 1.15bo the sync dialog and the records

- `decision_filter_lines` was O(N²): for every included item it scanned every excluded directory. A comparison with stashed directories therefore froze while the dialog opened. The excluded directories are now in a set, so the check is linear in the number of items.
- The sync confirmation dialog shows "Preparing the synchronization..." with a busy bar and repaints while it is built, so the button is seen.
- The progress label of the comparison now says how many items have been found, updated as the dry run writes them.

## 1.15bm the overview fits the statistics

- The overview pane starts wide enough (580 px) and defaults to 620 px, so
  the "Selected:" line and the six per-action counts are never clipped.
- The per-action values get 30 px instead of 22 px, which is enough for a
  three-digit count.

## 1.15bo the size and the time columns

- The size and the modified columns of the comparison list are sized for ten
  and twenty-one characters, so a long size or a timestamp does not get
  clipped. Saved states that carry a narrower width are widened to the same
  minimum.

## 1.15bo the overview fits the statistics

- The "Selected:" heading is now a tooltip on the summary label, with a
  short description of what it counts. The overview pane starts 580 px wide
  and defaults to 620 px, so the whole "Selected:" line and the six
  per-action counts fit with three-digit numbers.
- The size and the modified columns of the comparison list are sized for
  ten and twenty-one characters, and saved states that carry a narrower
  width are widened to the same minimum.
- The modified columns are hidden by default; the modification time is
  shown in the tooltip of the action column instead.

## 1.15bo the overview and the sync dialog

- The "Selected:" heading is a two-line tooltip on the whole statistics bar.
- The overview pane starts 480 px wide and defaults to 540 px, so the
  statistics bar is not clipped without being too wide.
- The sync dialog's command stops growing once it is fully visible; the
  decision rules keep the free space.
- The progress bar is reset when the sync dialog is dismissed.
- The terminal no longer shows the harmless KDE/Qt notices about the socket
  and the OpenGL context.
- The open buttons of the source and destination use the cloud-upload and
  cloud-download icons. The "Source" and "Destination" labels and the arrow
  above the action filters are gone, so the row is shorter.

## 1.15bp the column menu and the modified column

- The header context menu now applies the column visibility right away, so
  toggling a column updates the panes immediately.
- The modified columns can be shown again after they are switched off: the
  default hidden set is kept separate from a saved empty set.

## 1.15bp the overview shows "Keep in destination"

- The statistics bar now shows "Keep in Destination" (the count of the
  destination-only items that are kept) instead of an "Unchanged" entry that
  was always zero, because the comparison plan contains no unchanged items.

## 1.15bp the selected size

- "Selected:" now shows the total size of the items that are checked, so it
  matches the total of the comparison when everything is checked. The bytes
  that will actually be written stay in the plan summary and the confirmation
  dialog.

## 1.15bo the item column and the size column

- The item column takes the free space by default and stays resizable. Once
  it is resized by hand, the last visible column absorbs the free space, so
  the right edge of the header sticks to the view.
- The size column is sized for eight characters.

## 1.15bp the overview pane

- The overview pane starts 460 px wide and defaults to 500 px, so the
  statistics bar is not clipped without taking too much room.
- Loading a profile now refreshes the startup status, so the "Enter locations
  to compare" message is replaced with the proper state.

## 1.15bq the item column and the size column

- The item column takes the free space by default and stays resizable. Once
  it is resized by hand, the last visible column absorbs the free space, so
  the right edge of the header sticks to the view.
- The size column is sized for nine characters, which fits "999.9 KiB".
- The modified column is sized for nineteen characters.
- The overview pane's size column is the same width as the one in the
  comparison panes.

## 1.15bq the item column and the size column

- The item column takes the free space by default and stays resizable. Once
  it is resized by hand, the last visible column absorbs the free space, so
  the right edge of the header sticks to the view. The growth is capped so
  the size column cannot become absurdly wide.
- The size column is sized for nine characters, which fits "999.9 KiB".
- The modified column is sized for nineteen characters.
- The overview pane's size column is the same width as the one in the
  comparison panes.

## 1.15bp the item column and the size column

- The item column takes the free space by default and stays resizable. Once
  it is resized by hand, the last visible column absorbs the free space, so
  the right edge of the header sticks to the view. The growth is capped so
  the size column cannot become absurdly wide.
- The size column is sized for eleven characters, which fits "999.9 KiB"
  and "1,234,567 B".
- The modified column is sized for nineteen characters.
- The overview pane's size column is the same width as the one in the
  comparison panes.

## 1.15bp the overview pane

- The overview pane starts 474 px wide and defaults to 514 px, so the
  statistics bar is not clipped without taking too much room.

