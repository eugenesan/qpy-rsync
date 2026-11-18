# Roadmap and milestones

This document is the single place for the milestones of qpy-rsync: what has
been delivered, how it was validated, and what is planned. The detailed
history of every change is in [`../CHANGELOG.md`](../CHANGELOG.md); the design
that the milestones implement is in [`design.md`](design.md).

## How the milestones work

Every milestone must

- keep the full Git history,
- pass the complete test suite,
- compile the Python sources,
- and be delivered as a Git-generated downloadable patch.

A milestone that changes the runtime behaviour also needs a focused manual
smoke test, which is recorded below.

## Delivered milestones

The milestones 1 through 1.15bd are described in the changelog, one section
each. In short:

| Milestone | Delivered |
|---|---|
| 1 | the local comparison with a dry run and a read-only list |
| 1.1 – 1.10 | the parser, the destination inventory, the SSH endpoints, the askpass helper, the process environment |
| 1.11 | the installation and the development documentation |
| 1.12 | the external diff tool |
| 1.13 | the comparison usability: filtering, the panes, the saved state |
| 1.14 | the per-object decisions |
| 1.15a | the persistent include and exclude filters |
| 1.15b | the backup directory and the nested protection |
| 1.15c | the immutable execution plan and the verification dry run |
| 1.15d | the confirmation and the write-capable synchronization |
| 1.15e – 1.15z | the progress, the inventory mode, the profiles, the command preview and the review fixes |
| 1.15aa – 1.15al | the toolbar, the icons, the journal, the diff staging and the expansion limits |
| 1.15am – 1.15ap | the flat comparison list that replaced the tree |
| 1.15aq – 1.15az | one comparison view, the settings, the statistics, the columns, the stash and the folding |
| 1.15ba – 1.15bd | the quiet terminal, the parent folder, the external tools and the inverted action filter |
| 1.16 | profiles, recent profiles and the profile editor; desktop integration and launcher scripts; packaging dependencies. The original 1.16 goals were met along the way and need no separate milestone. |

## Milestone validation notes

The notes below record how the early milestones were checked on a real
machine. They are kept as the reference for the repeatable smoke tests.

### milestone 1: the local smoke test

```bash
rm -rf /tmp/qpy-rsync-source /tmp/qpy-rsync-destination
mkdir -p /tmp/qpy-rsync-source/sub /tmp/qpy-rsync-destination
printf 'new\n' > /tmp/qpy-rsync-source/new.txt
printf 'changed-new\n' > /tmp/qpy-rsync-source/changed.txt
printf 'changed-old\n' > /tmp/qpy-rsync-destination/changed.txt
printf 'destination-only\n' > /tmp/qpy-rsync-destination/old.txt
chmod 755 /tmp/qpy-rsync-source/new.txt
```

Select the two directories and click **Compare**. The milestone performs only
`rsync --dry-run`; it never synchronizes or deletes. The expected changes are
`new.txt`, `changed.txt` and `sub/`.

### milestone 1.1: the completion fix

The first runner converted `QProcess.ExitStatus` with `int()`. The enum
conversion differs between the PySide6 releases, and the resulting `TypeError`
left the window showing *Comparing...* after rsync had exited. The runner now
compares the enum directly, drains the final output and always forwards the
result, so the status changes to *Comparison completed*.

### milestone 1.4: the comparison smoke test

Compare the same trees and verify that the three panes stay synchronized, that
a source-only row shows *create*, that a destination-only row shows *keep*
while the deletion is disabled, that a destination-only file shows no
`Unknown`, no size `0` and no epoch timestamp, and that a local path starting
with `~/` is expanded.

### milestone 1.7: the askpass display fix

The controlled output format does not need a locale-dependent parser, so
qpy-rsync no longer forces `LC_ALL=C`; the askpass helper otherwise read it
as the non-UTF-8 `ANSI_X3.4-1968` locale. When `WAYLAND_DISPLAY` is present
and `QT_QPA_PLATFORM` is not set explicitly, the askpass child receives
`QT_QPA_PLATFORM=wayland`. The complete inherited desktop environment still
supplies `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS`.
If neither a Wayland nor an X11 session is present, the password
authentication is blocked before rsync starts.

### milestone 1.8: the X11 askpass fix

The trace of milestone 1.7 showed the platform but an empty display name, so
the session values are now inserted into the process environment explicitly:

```text
DISPLAY
XAUTHORITY
DBUS_SESSION_BUS_ADDRESS
XDG_RUNTIME_DIR
WAYLAND_DISPLAY
```

The values stay visible in the debug mode so that a display authentication can
be diagnosed precisely. They are session endpoints, not passwords, but the
paths and the user names should still be reviewed before a log is shared.

## The delivery gate

Before a milestone is delivered:

```bash
git apply --check milestone.patch
git apply milestone.patch
git diff --check
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest -q
/usr/bin/python3 -m compileall -q src
```

A milestone that changes the runtime behaviour also needs the focused manual
smoke test that its section describes.

## Planned work

### Milestone 1.15be: responsive comparison and search (in progress)

Measured on the 1.2M-item tree (`timing20.txt`, 520,663 changes,
31,242 folders). The numbers are model time plus the overview time for one
user action:

| Action | timing18 | timing19 | timing20 |
|---|---|---|---|
| Global filter | ~1.7 s | ~1.46 s | **~1.04 s** |
| Single decision | ~0.9 s | ~0.5–1.1 s | **~0.5 s** |
| Show stashed | ~1.5 s | ~1.3 s | ~1.2–2.0 s |
| Initial compare | ~3.5 s | ~3.5 s | ~3.9 s (acceptable) |

Delivered so far: flat rows with O(1) position maps, one-pass filter and
totals, cached effective actions, and a persistent Overview tree whose folder
nodes are reused across filter changes.

Remaining work, in priority order:

1. **Incremental Overview totals — delivered.** `ui.overview_update` was 260–290 ms
   for a single decision. `set_aggregates()` currently recomputes every folder
   total, sort order and visible-child list. Compare the new counts with the
   old ones and update only the changed folders and their ancestors; rebuild
   the view lists only where a folder actually becomes empty or non-empty.
   Target: under ~40 ms for a decision, under ~100 ms for a global filter —
   measured at 19–21 ms for a single folder on a 31k-folder tree, 49 ms for
   half the folders.
2. **Remove the change-list copy in `view.emit_changes` — delivered.** The
   `changes_updated` signal now carries only the reason string; the slot pulls
   aggregates from the model. No 520k-element list is copied on every action.
3. **Speed up `refresh_excluded_visibility()` — delivered.** The excluded
   flags are applied inside the single row rebuild pass instead of a separate
   O(n) loop. A show/hide toggle on a 31k-folder tree dropped from ~500 ms to
   ~330 ms.
4. **Indexed incremental search — delivered.** Folded names and paths are
   cached on the model, the match list is built once per search text, and
   Enter/Shift+Enter step through it in O(1). Typing searches after a 250 ms
   debounce, a `n/total` counter is shown, and Ctrl+G / Ctrl+Shift+G repeat the
   search from anywhere in the window. F3 stays with Load Profile. Search never
   changes the visible set.
5. **Coalesce UI refreshes — deferred.** After the items above, one user
   action triggers one Overview update in the current signal graph. A timer
   debounce would help only with rapid repeated clicks, at the cost of
   asynchronous state in the tests; revisit if `timing` shows duplicated work.

Acceptance: every compare-view action, including search and global filters,
under ~1 s on the 1.2M-item tree; initial load unchanged.

### Milestone 1.15bf: finish the unified lists — delivered

The stash was a useful stepping stone, but it was a second exclusion system
next to the per-item decisions. It is gone; there is one model of "this item
is not part of this run": an EXCLUDE decision.

1. **Remove the stash and unify it with decisions.**
   - Space, the context menu and the overview keep working, but they set the
     existing EXCLUDE decision instead of adding to `StashedItems`.
   - The "Show stashed" toggle becomes "Show excluded" and uses the same
     per-row `excluded` state as the decisions. "Restore All Stashed" becomes
     "Reset Excluded Decisions" (or is removed if the existing *reset all*
     already covers it).
   - `StashedItems`, `stash_path`, `stashed_paths`, `set_show_stashed` and the
     stash arguments of `build_execution_plan` are removed once all callers
     use the decisions. The plan fingerprint then has one source of truth.
   - Keep the regression tests: excluding a directory hides its descendants
     and protects its destination contents; excluded items stay out of the
     plan and the overview totals.
2. **Clean up the central action column.** The crossed-eye marker now paints
   the same state as the checkbox. Remove the duplicate marker and its click
   target; keep the checkbox as the single affordance for include/exclude.
   The action column should show only the action icon, label and checkbox.
   Update the delegate painting, the hit tests, the tooltips, the help text
   and the design document.
3. **Finish the unified list details.**
   - One selection path shared by all three panes, with no separate stash
     selection state.
   - The overview's hide/restore action uses the same decision API as the list.
   - The journal and statistics describe exclusions with one vocabulary.
   - No stale "stashed" strings in the UI, docs or tests.

Acceptance: the full suite passes, the help and design documents match the UI,
and a manual smoke test confirms that Space excludes a directory, all of its
children disappear from the list, and the destination is never touched.
Status: code, documents and tests updated; 367 tests pass. The manual smoke
test remains with the user, who is testing on real trees.

### After 1.15bf

- review the removal of the `/tmp/qpy-rsync-smoke` execution restriction
- harden the synchronization further and validate it on real trees
- refine the conflict policy of an existing destination object
- improve the rename and move detection
- extend the external tools with a per-tool working directory and a
  per-profile selection
