# qpy-rsync design

**Status:** consolidated design, v0.2
**Stack:** Python 3.11+, PySide6 6.7+, the external `rsync`, OpenSSH
**Target:** Linux desktop, KDE Plasma as the primary environment

This document is the single reference for the design, the architecture and
the specifications of qpy-rsync. It replaces the earlier `specification.md`,
`rsync-qt-gui-spec.md`, `architecture.md`, `comparison-ui.md`,
`endpoint-syntax.md`, `rsync-output-contract.md`, `ssh-authentication.md`,
`security.md`, `diff-tool-integration.md`, `repository-policy.md` and
`development-workflow.md` documents.

The development history lives in [`../CHANGELOG.md`](../CHANGELOG.md) and the
plan lives in [`roadmap.md`](roadmap.md). Installation and debugging are
described in [`installation.md`](installation.md) and [`debugging.md`](debugging.md).

## 1. Product vision

qpy-rsync is a graphical frontend for `rsync` that combines:

- rsync's POSIX metadata fidelity and transfer engine
- a FreeFileSync-like flat comparison list
- preview through `rsync --dry-run`
- per-object decisions before execution
- reusable profiles
- OpenSSH and desktop-managed authentication
- inspectable commands, progress, summaries, and logs

The application is a visualization, configuration and control layer. It does
not implement its own synchronization or delta-transfer engine. The preview and
the execution always use the same rsync backend with equivalent options.

## 2. Scope

### 2.1 In scope

- Local and SSH endpoints, one-way, source to destination
- Dry-run comparison with a flat, sortable and filterable list
- Per-object and per-subtree decisions
- Stashing items for the duration of one comparison
- Ordered rsync include/exclude filters
- Backup and versioning with a user-managed backup directory
- An immutable execution plan, a second verification dry run, and a final
  confirmation before anything is written
- Transfer progress, a journal, and a session log
- External diff tool and user-configured external tools
- Profiles and persistent settings
- Packaging for Linux

### 2.2 Deferred

- Bidirectional synchronization and a persistent conflict history
- Guaranteed rename/move detection
- Rsync daemon endpoints and module discovery
- Cloud APIs
- Windows as a first-class target
- Arbitrary regular-expression filters
- Remote-to-remote copies

## 3. Synchronization model

### 3.1 Direction

```text
Source -> Destination
```

The interface makes the direction unambiguous: the direction line above the
action filters names both sides, and the middle pane carries the action of
every row. A deliberate swap invalidates the active comparison plan.

### 3.2 Synchronization modes

- **Update** copies new and changed source objects and retains objects that
  exist only in the destination.
- **Mirror** makes the destination match the source and deletes destination-only
  objects with the configured delete timing (`--delete-during` by default).
- **New Only** copies objects missing from the destination with
  `--ignore-existing` and never updates or deletes an existing object.

Changing the mode invalidates the comparison, because the same path can change
from *keep* to *delete* or from *update* to *keep*.

### 3.3 Global policy

For a destination object that would be changed or replaced:

- **Override:** take the action rsync proposed; the default
- **Skip:** protect the object from the run
- **Unselect:** show it unchecked until the user selects it

"Conflict" is a user-interface term here. qpy-rsync keeps no bidirectional
state database, so there is no historical three-way conflict.

### 3.4 Per-object actions

Each actionable row uses checkbox semantics:

- checked: execute the displayed action
- unchecked: skip or protect the displayed action
- inherited directory decisions apply to the descendants unless a child
  overrides them

In Update and New Only, destination-only rows default to unchecked *keep*.
Checking one turns the effective action into *delete*. In Mirror, deletion rows
default checked; unchecking protects them. The action-pane context menu resets
one decision, a subtree, or every manual decision.

Rsync cannot consume an arbitrary action graph. qpy-rsync therefore converts
the decisions into an ordered temporary rsync filter file, and destination-only
objects that are deselected are protected explicitly when deletion is enabled.

Before the transfer, a second dry run recreates that filter and compares path,
action and object kind with the included plan. A mismatch blocks the execution.

### 3.5 Stashed items

An item can be **stashed** with the space bar, with the crossed-eye marker in
the action column, or from the context menu. A stashed item

- is left out of the execution plan,
- stays in the comparison, so it can be restored,
- is forgotten when the next comparison starts.

The stash lives in memory only. The filter bar has a *Show stashed items*
toggle, and its right-click menu offers *Restore All Stashed*. The context
menu of the action pane offers the same for the whole list.

Stashing is deliberately distinct from folding (see 4.5) and from the rsync
filters (see 6): it is a temporary, per-comparison exclusion.

### 3.6 Plan freshness

The immutable plan records:

- a semantic profile fingerprint that excludes labels and random identifiers
- the source and destination operands
- the comparison action and the effective execution action
- the object path and kind
- the included, unchecked, retained, destructive, operation and backup counts

The verification dry run recreates the private decision filter and compares
path, action and object kind with the included plan. Confirmation is blocked
after any material mismatch or freshness change.

## 4. Comparison and user interface

### 4.1 Dry-run contract

The backend uses an argument-vector equivalent of:

```text
rsync --dry-run --itemize-changes --out-format=<controlled-record> [OPTIONS] SOURCE DESTINATION
```

Requirements:

- keep stdout and stderr separate
- parse only the requested record format
- reject malformed records instead of guessing
- retain the raw itemized-change code
- detect filenames that the selected output framing cannot represent
  unambiguously

The output parser is a versioned internal protocol boundary. The controlled
record format carries a visible field token (`|qpy-rsync|`); a filename that
contains it stops the parsing with an ambiguity error instead of silently
producing a wrong plan.

### 4.2 The flat list

The comparison is a flat list, modelled after the FreeFileSync file grid. The
hierarchy is painted, not modelled: a directory row is followed by its own
items, then by its subdirectories. The model is a plain table model, so the
views ask only for the rows they paint, and a comparison of hundreds of
thousands of items costs the same as a small one.

The three panes (source, action, destination) share one model and stay
synchronized in selection and vertical scrolling.

### 4.3 Panes and columns

The name column of each side carries the relative path, the item count, the
size and the modification time. The item, count and date columns can be
switched off from the header context menu; the choice is remembered per pane.

### 4.4 Normalized actions

- Create file, directory or symlink
- Update content
- Update size or time
- Update metadata only
- Replace the object type
- Delete the destination object
- Skip or protect
- Unchanged
- Error or unsupported

### 4.5 Folding

A directory row carries a branch marker. Clicking it folds the directory's
contents out of the list, and clicking it again brings them back. Folding is
view-only:

- the sync, the totals, the statistics and the overview keep every item
- a path filter temporarily overrides the folds, so a search never loses a
  match; clearing the filter restores them
- selecting a path from the overview or from a filter expands its ancestors
  first
- the folds live in memory and are cleared with the next comparison

The compared folder itself is the parent of the tree: it has no branch marker
and is never folded.

### 4.6 The action filter bar

The bar above the panes carries one checkbox per action, plus the *unchanged*
and the *stashed* toggles. It filters the view only; it never changes what is
synchronized.

- A plain click toggles one action.
- Ctrl+click inverts the bar: the clicked action becomes the only one that is
  shown, and a second inverted click shows everything but that action.
- The context menu of every checkbox offers *Show only this*, *Show everything
  but this*, *Show all* and *Reset to default*.

### 4.7 The path filter

The filter field matches the name of an item, or its relative path when the
pattern contains a slash. Shell-style globs are supported (`*`, `?`, `[...]`).
A pattern that ends with a slash matches directories only and keeps their
contents.

### 4.8 The overview

The overview pane summarizes the comparison as a tree of folders with their
share, item count and size, and carries the statistics of the current
selection. It can hide and restore folders with the same stash semantics as
the comparison list.

## 5. Endpoints and transport

### 5.1 Endpoint syntax

Both sides accept the same syntax.

Local:

```text
/home/alice/data
~/data
```

`~` is expanded by qpy-rsync. A directory means "the contents of the
directory", which is the rsync operand `/data/project/`.

SSH:

```text
server:/srv/data
alice@server:/srv/data
nas-alias:/backup/documents
```

This is rsync's remote-shell syntax, not a URL. `nas-alias` may be a `Host`
alias from `~/.ssh/config`, including its `User`, `Port`, `IdentityFile` or
`ProxyJump`. Authentication is handled by OpenSSH and the active
`ssh-agent` or desktop key manager.

Constraints:

- the remote path must be absolute, or start with `~/`
- at most one side may be remote
- `host::module` and `rsync://` daemon syntax are not supported

### 5.2 Supported combinations

- local to local
- local to SSH
- SSH to local

Remote to remote is refused.

### 5.3 SSH authentication

qpy-rsync delegates authentication to OpenSSH. For remote comparisons it sets:

```text
SSH_ASKPASS=/path/to/discovered/helper
SSH_ASKPASS_REQUIRE=force
```

`SSH_ASKPASS_REQUIRE=force` needs OpenSSH 8.4 or later and makes SSH use the
graphical helper for password and key-passphrase requests even when terminal
detection would choose a TTY.

The helper is discovered in this order:

1. the executable path already set in `SSH_ASKPASS`
2. `ksshaskpass`
3. `ssh-askpass`
4. `ssh-askpass-gnome`
5. `gnome-ssh-askpass`

For KDE Plasma, install the distribution's `ksshaskpass` package; it can
integrate with KWallet. Key-based authentication through an unlocked agent
remains preferable, because it avoids repeated prompts.

The askpass child receives the inherited desktop session explicitly, so the
helper can open a window:

```text
DISPLAY
XAUTHORITY
DBUS_SESSION_BUS_ADDRESS
XDG_RUNTIME_DIR
WAYLAND_DISPLAY
QT_QPA_PLATFORM        (wayland, when the session provides it)
```

If no helper is found, the remote operation is blocked with an installation
message instead of letting rsync hang. A changed host key stays a hard
failure; qpy-rsync never bypasses OpenSSH host-key verification.

## 6. Filters

The filter editor maintains one ordered list of persistent rules that apply to
both the comparison and the execution. The first matching rsync rule wins.

Three rule types are supported:

- **Include** generates `--include=PATTERN`
- **Exclude** generates `--exclude=PATTERN`
- **Advanced** generates `--filter RULE` for native rsync filter syntax

Rules can be enabled or disabled without being removed. Disabled rules keep
their position, type, pattern and comment, but they are left out of the
argument vector. Import reads native rsync filter-file lines as advanced
rules; export writes the enabled rules in native filter-file syntax.

Rsync must be allowed to traverse the parent directories before it can match an
included descendant, so a single file needs both:

```text
Include  /.git/
Include  /.git/HEAD
Exclude  /.git/***
```

Changing the rules keeps the previous comparison visible but marks it stale,
and the decision checkboxes are locked until a new comparison succeeds.

## 7. Backups and versioning

A non-empty backup directory enables rsync backups for the destination objects
that rsync alters or removes. qpy-rsync always uses `--backup` together with
`--backup-dir`; clearing the field disables the backups. The naming, the
rotation, the retention and the cleanup of the backups stay with the user.

The backup path is interpreted on the destination side. For an SSH destination
it is a path on that remote host without the `host:` syntax. A local backup
path may use `~`, which qpy-rsync expands before the command is generated.

The application reports whether a local backup directory is missing, empty,
non-empty or unavailable for inspection. A missing directory may be created by
rsync. A non-empty directory is allowed, but newer backups may replace older
files with the same relative path.

When the backup directory lies inside the source or destination tree, the
protection of the nested backups is enabled by default. Two rules are injected
before the user rules:

```text
P /relative-backup-path/***
- /relative-backup-path/***
```

The protect rule prevents a deletion on the destination side; the exclude rule
prevents the normal traversal and transfer. The protection can be disabled
explicitly, which produces a warning.

## 8. Required rsync options

The profile editor supports the options that change the meaning of a run:

| Option | Meaning and warning |
|---|---|
| `--copy-links` | Copy the link targets; may traverse outside the apparent tree |
| `--whole-file` | Disable the delta transfer; useful for local copies |
| `--relative` | Preserve the source path structure; the source spelling matters |
| `--no-compress` | Disable the compression where a preset enabled it |
| `--inplace` | Modify the files in place; weaker interruption safety |
| `--delete` | Remove the destination-only objects; destructive |
| `--numeric-ids` | Preserve the numeric IDs; they may not map meaningfully |
| `--one-file-system` | Do not descend into additional mounted file systems |
| `--sparse` | Recreate the sparse files where possible |
| `--ignore-times` | Transfer every file regardless of the quick check |

The delete timing can be *before*, *during*, *delay* or *after*. The fuzzy
rename optimization selects `--delete-after` unless it is disabled explicitly.
A centralized compatibility validator reports the unsafe or contradictory
combinations.

## 9. Profiles and persistent settings

A profile holds the source and destination endpoints, the method, the
decision rules, the backup settings and the option set. The profiles are
stored as versioned JSON in `$XDG_CONFIG_HOME/qpy-rsync/profiles`, and the
application settings live in `$XDG_STATE_HOME/qpy-rsyncstaterc`.

The settings dialog has the pages *General*, *Logging*, *Backup* and *Tools*.
The general page holds the completion sound, the logging page the log file
and the backup page the backup directory, and the tools page the external
tools and the diff tool command.

## 10. Progress, logs and cancellation

A transfer reports its progress, its phase and the number of processed
objects; the journal keeps the commands, the itemized records and the
application states, while the raw rsync progress belongs in the session log
file, so the journal stays readable.

The status bar carries the operation state only. Every other message goes to
the journal with a `HH:MM` timestamp and a severity colour.

The execution gate is an explicit state machine: a transfer may only start
after a successful verification and an explicit confirmation, and a cancelled
or failed run stays visibly incomplete.

## 11. External tools

The tools page of the settings lists the tools that the context menu of a row
offers. A tool is a command with placeholders:

| Placeholder | Meaning |
|---|---|
| `%a` | the full path of the item in the pane that was clicked |
| `%f` | its file name |
| `%x` | its extension |
| `%b` | its file name without the extension |
| `%d` | its directory |
| `%A` | the full path of the item in the other pane |
| `%F` | its file name |
| `%X` | its extension |
| `%B` | its file name without the extension |
| `%D` | its directory |
| `%R` | the host of the other pane, empty when it is local |
| `%U` | the user of the other pane, empty when it is local |
| `%V` | `@` when the other pane has a user |
| `%W` | `:` when the other pane has a host |
| `%P` | `://` for a remote pane, empty for a local one |
| `%T` | the name of the tool |
| `%O` | the options of the tool |
| `%%` | a literal percent |

The command is split into words before the placeholders are filled in, so a
path with a space stays one argument. A placeholder without a value leaves
nothing behind. Examples:

```text
kate %d/%f
meld %D %d
scp %d/%f %U%V%R%W%D/%F
```

The diff tool follows the same placeholders. When its command is empty,
qpy-rsync resolves a tool the way Git does (`diff.guitool`, `diff.tool`,
`difftool.<tool>.path`) and falls back to meld, kdiff3, kompare or vimdiff. A
remote file is staged in a private temporary directory before the tool is
started.

## 12. Architecture

### 12.1 Layers

- `gui`: presentation only
- `core`: transport-independent models and validation
- `backend`: process invocation, parsing, probes and filter generation
- `storage`: profiles, settings, migrations and logs
- `services`: the workflows that coordinate the other layers

The GUI never handles file contents. All rsync and SSH calls use argument
vectors through `QProcess`, never a shell.

### 12.2 Module map

```text
qpy-rsync/
  README.md
  CHANGELOG.md
  pyproject.toml
  docs/
    design.md            this document
    roadmap.md           the plan and the milestone history
    installation.md      the runtime and the development setup
    debugging.md         the diagnostics
  src/qpy_rsync/
    app.py               the entry point and the Qt environment
    cli.py               the command line for the command preview
    core/               models, endpoints, decisions, the execution plan
    backend/            rsync commands, the parser, the inventory, SSH
    services/           comparison, sync, verification, inventory, tools
    storage/            the profiles and the settings
    gui/                the window, the comparison list, the dialogs
  tests/
    unit/
    fixtures/
  tools/                the helper scripts
```

### 12.3 Data flow

1. The window collects the endpoints and the method.
2. The compare service builds the rsync argument vector and runs the dry run.
3. The parser normalizes the itemized records into changes.
4. The flat model turns the changes into the rows of the list, and the filters
   decide which rows are shown.
5. The overview and the statistics summarize the visible changes.
6. The execution plan snapshots the selected actions.
7. The verification service runs the second dry run with the private filter.
8. The sync service runs the write-capable rsync with the same filter.

## 13. Security and reliability baseline

- Never use `shell=True` and never concatenate a command for execution.
- Keep the SSH host-key verification enabled.
- Store no password, passphrase or private key.
- Redact the credentials and the environment values from the diagnostics.
- Use private temporary filter files, and remove them on every result path.
- Require a successful verification before a destructive execution.
- Treat `--delete`, `--inplace` and `--copy-links` as high-visibility options.
- Keep the execution restricted to disposable local paths until the
  cancellation and failure handling have matured.

## 14. Testing strategy

- The whole suite runs headless with `QT_QPA_PLATFORM=offscreen`, and Qt
  warnings are fatal.
- The window is never shown in a test; the widgets are built and driven
  directly.
- Every module has unit tests, and the end-to-end workflows of the window, the
  comparison list, the overview and the settings have their own.
- The parser has fixtures for the supported rsync versions.
- The real transfer is exercised with disposable fixtures under
  `/tmp/qpy-rsync-smoke`, using the scripts in `tools/`.

## 15. Delivery policy

- The working representation is a Git repository with `main` as its default
  branch.
- Every completed increment is committed before it is delivered.
- A delivery includes the tests, the test commands, a changelog entry and a
  suggested commit message.
- The release archives include the complete Git history, and the worktree of
  an archive is verified to be clean.
- The generated caches, the virtual environments, the build outputs and the
  secrets stay excluded.

## 16. Open questions

- The rename and move optimization is optional and never authoritative; the
  `--fuzzy --delete-after` pair may change the timing of the deletions.
- The conflict policy of an existing destination object is a user-interface
  term; a real conflict database is out of scope.
- The remote browsing of an SSH host is limited to a manual path today.
