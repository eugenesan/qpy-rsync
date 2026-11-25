# qpy-rsync

`qpy-rsync` is a graphical frontend for `rsync` for the Linux desktop. It
compares two locations with a real `rsync --dry-run`, shows what would change
in a flat, sortable list, lets you decide item by item what to do, and only
writes after you have reviewed the plan and confirmed it. It speaks the rsync
dialect you already know, keeps every command inspectable, and never touches a
file without a preview in front of it.

The application is a visualization, configuration and control layer. It does
not implement its own transfer engine: the preview and the synchronization
always run the same `rsync` with equivalent options. The native Qt comparison
views are the default; the Python views remain as a fallback.

![The main window of qpy-rsync](resources/main-window.png)

## What it does

- compares a local folder with another local folder, or with one folder on a
  remote host over SSH
- shows the source, the decision and the destination of every item in one flat
  list, with the folders painted as a hierarchy
- lets you include or exclude items, whole folders or a whole comparison
- excludes items for the duration of one comparison, and folds folders away
  while you read a large tree
- keeps one ordered list of rsync include and exclude rules, with a live
  preview of the command
- takes a backup of everything it changes, in a directory you choose
- optionally verifies the selection with a second dry run, and asks for an
  explicit confirmation before it writes anything
- reports the progress, keeps a journal of every command, and logs the raw
  rsync output in a session file
- opens an item in an external diff tool, or in any external tool you
  configure
- summarizes the folders in an overview with item counts, sizes, shares and the
  same decisions as the list

## Using it

### 1. Enter the two locations

Both fields accept the same syntax:

```text
/home/alice/data          a local folder
~/data                    a local folder, ~ is expanded
server:/srv/data          a folder on a remote host
alice@server:/srv/data    a folder on a remote host, with a user
```

At most one side may be remote. `Host` aliases from `~/.ssh/config` work as
they do for `rsync`. Press **Enter** in the destination field to start the
comparison when both sides are filled in.

### 2. Choose the method

| Method | Behaviour |
|---|---|
| **Update** | copies new and changed items, keeps what only exists in the destination |
| **Mirror** | makes the destination match the source, deleting the items that only exist there |
| **New Only** | copies only the items that are missing in the destination |

Changing the method after a comparison marks it stale and asks for a fresh
Compare. **Preserve Decisions** stays as you set it.

### 3. Compare

**Compare** (F5) runs `rsync --dry-run`. The list fills with the items that
rsync reported, grouped by folder. The three panes stay synchronized: the
source on the left, the decision in the middle, the destination on the right.

The decision pane carries a checkbox for every item that can be decided.
Checking an item includes it in the synchronization, unchecking it excludes
it. A folder decides for everything below it, and a child can override its
folder. The **Preserve Decisions** button beside Compare keeps manual
decisions across the next comparison.

### 4. Filter, fold and exclude

The filter field above the panes matches the names of the items, or their
relative path when the pattern contains a slash. Shell-style globs work
(`*.jpg`, `file?.txt`, `[0-9]*`). A pattern that ends with a slash matches
the folder with that name exactly, and retains its complete subtree.

```text
guide        matches names containing "guide"
*.py         matches Python filenames
file?.txt    uses ? for one character
[0-9]*       matches names beginning with a digit
*            shows all changed objects
.            matches names containing a literal period
docs/        matches the docs folder exactly and retains its subtree
```

The branch marker in front of a folder folds its contents out of the list.
Folding is a view-only operation: the synchronization, the totals and the
overview keep every item.

**Space** excludes the selected item. An excluded item is left out of the
synchronization, stays in the comparison so that you can restore it, and is
forgotten with the next comparison. The crossed-eye marker in the decision
column excludes and includes an item, the *Show excluded items* toggle in the
filter bar reveals them, and its right-click menu offers *Reset All
Exclusions*.

The checkboxes above the panes filter the list by decision. A plain click
toggles one decision, **Ctrl+click** inverts the bar so that only the clicked
decision is shown, and the right-click menu of a checkbox offers *Show only
this*, *Show everything but this*, *Show all* and *Reset to default*. The
folder toggle next to them applies the same filters to reported directories:
off, directories ignore the decision filters; on, a directory whose own
change is filtered out stays as a faded parent when it still contains visible
items.

### 5. Verify and synchronize

**Verify Decisions** (F8) builds an immutable plan of your selection and runs
a second dry run with it. If the result differs from what you see, the
execution is blocked and the difference is reported. Verification is optional
and its toolbar button is hidden until **Settings → Advanced → Show the Verify
Decisions check** is enabled.

**Synchronize** (F9) opens the confirmation dialog with the endpoints, the
counts, the destructive operations and the backup configuration. Only after
you confirm, a write-capable `rsync` runs with the verified plan. The
comparison is then marked stale; it is up to you to press Compare when you
want a fresh view, so the journal still shows what the sync just did.

![The confirmation dialog of a synchronization](resources/sync-dialog.png)

### Overview

The overview summarizes the comparison by folder. **Total** carries the whole
selection, the synthetic **Files** row lists the objects that live in the
compared folder itself, and every folder shows its items, size and share of
its parent. A reported directory counts as one item of its parent; synthesized
navigation folders and faded, filtered-out parents do not. The overview follows
the same decision filters as the list, starts collapsed, and sorts by share by
default. Click the **go-jump** icon to the left of a folder to reveal it in the
comparison panes; a normal click still selects and expands the folder.
**Ctrl+Tab** cycles Normal, Compare only and Compare with overview.

### Filters, backups and profiles

- **Filters** (F7) maintains the ordered include and exclude rules. The first
  matching rsync rule wins, and the rules apply to the comparison and to the
  execution.
- The **backup directory** turns on rsync's `--backup` for everything that is
  changed or removed on the destination. When the backup folder lies inside
  the compared tree, it is protected automatically.
- **Save Profile** (F2) and **Load Profile** (F3) store the endpoints, the
  method, the rules and the backup settings.

### External tools

The settings have a *Tools* page that lists the tools the context menu of a
row offers. A tool is a command with placeholders:

| Placeholder | Meaning |
|---|---|
| `%a` | the full path of the item in the pane you clicked |
| `%f` | its file name, `%x` its extension, `%b` the name without it |
| `%d` | its directory |
| `%A` | the full path of the item in the other pane |
| `%F` | its file name, `%X` its extension, `%B` the name without it |
| `%D` | its directory |
| `%R` `%U` `%V` `%W` `%P` | the host, the user, `@`, `:` and `://` of the other pane |
| `%T` `%O` | the name and the options of the tool |
| `%%` | a literal percent |

```text
kate %d/%f
meld %D %d
scp %d/%f %U%V%R%W%D/%F
```

The same page holds the command of the diff tool. An empty field keeps the
tool that the system offers, with the preference of Git.

![Settings, including the decision colours](resources/settings-dialog.png)

### Keyboard

| Key | Action |
|---|---|
| F1 | the how-to |
| F2 / F3 | save and load a profile |
| F4 | edit the profile |
| F5 / F6 / F7 | compare, inventory, filters |
| F8 / F9 | verify the decisions, synchronize |
| F10 / F11 | cancel a running operation, pause it |
| F12 | cycle the synchronization method |
| Ctrl+F | focus the filter field |
| Ctrl+G / Ctrl+Shift+G | find next / previous |
| Ctrl+Tab / Ctrl+Shift+Tab | next / previous layout |
| Ctrl+, | the settings |
| Ctrl+Z / Ctrl+Shift+Z | undo / redo a decision |
| Space | exclude the selected item |
| Left / Right | fold and unfold a folder |
| Ctrl+click | invert the decision filter |
| Ctrl+Q | quit |

## Requirements

- Linux with Python 3.11 or newer
- rsync 3.x
- OpenSSH for the remote endpoints
- PySide6 6.7 or newer for the interface
- `setsid` from util-linux for remote operations
- an askpass helper (`ksshaskpass`) for the password prompts of a remote host
- optionally, Qt 6 development packages, CMake, Ninja and nanobind to build
  the native comparison views; the Python views work without them

The runtime packages, the optional virtual environment, the development
packages and the SSH prerequisites are described in
[`docs/installation.md`](docs/installation.md).

## Installation

Run the checkout with the system Python of Ubuntu:

```bash
./qpy-rsync.sh
```

The runners resolve the checkout themselves and work from any directory.
`./qpy-rsync-test.sh -q` runs the whole test suite, compiles the sources and
checks the diff.

To build the Debian package:

```bash
dpkg-buildpackage -us -uc -b
sudo apt install ../qpy-rsync_0.4.0-0_amd64.deb
```

The package installs the launcher, the desktop entry, the icon and the native
Qt view extension when Qt 6 is available.

## Development and debugging

- [`docs/installation.md`](docs/installation.md) — the runtime, the
  development packages and the test commands
- [`docs/debugging.md`](docs/debugging.md) — the console diagnostics of a run
- [`native-hybrid/README.md`](native-hybrid/README.md) — the native Qt view
  extension

## Documentation

| Document | Content |
|---|---|
| [`docs/design.md`](docs/design.md) | the design, the architecture and the specifications |
| [`docs/roadmap.md`](docs/roadmap.md) | the milestones, their validation and the plan |
| [`docs/installation.md`](docs/installation.md) | the installation, the development setup and the SSH prerequisites |
| [`docs/debugging.md`](docs/debugging.md) | the diagnostics of a run |
| [`CHANGELOG.md`](CHANGELOG.md) | the history of every change |

## Safety status

This is pre-alpha software. The synchronization is implemented and validated,
and the execution is no longer restricted to a disposable smoke tree. The
explicit confirmation, the optional second dry run and the profiles protect a
comparison before it is written. The application never runs a command through
a shell.

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
