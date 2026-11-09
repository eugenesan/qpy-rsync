# qpy-rsync: Product Specification and Implementation Plan

**Status:** Initial specification, v0.2  
**Project name:** qpy-rsync  
**Target:** Linux desktop, with KDE Plasma as a primary environment  
**Stack:** Python 3, PySide6, external `rsync`, OpenSSH  
**Initial scope:** One-way local and SSH synchronization with dry-run preview, per-object controls, profiles, progress, and backups

## 1. Product vision

qpy-rsync is a modern graphical frontend for `rsync` combining:

- rsync's POSIX metadata fidelity and transfer engine
- a FreeFileSync-like visual comparison tree
- preview through `rsync --dry-run`
- per-object decisions before execution
- reusable profiles
- OpenSSH and desktop-managed authentication
- inspectable commands, progress, summaries, and logs

The application is a visualization, configuration, and control layer. It does not implement a separate synchronization or delta-transfer engine. Preview and execution must use the same rsync backend and equivalent options.

## 2. Confirmed product decisions

- Project name: **qpy-rsync**
- UI toolkit: **PySide6**
- Backend: the external `rsync` executable, invoked with argument vectors through `QProcess`
- Initial direction: **one-way**, source to destination
- Supported endpoint combinations: local-to-local, local-to-SSH, and SSH-to-local
- Rsync daemon transport and module discovery are **out of scope**
- No hidden synchronization database in v1
- Default overwrite policy: **Override**
- Alternative policies: **Skip** and **Unselect pending manual selection**
- Every proposed action can be toggled manually, subject to a validation dry-run
- Changed-only and all-objects views are required
- Object metadata columns are configurable
- Fuzzy rename optimization uses `--fuzzy --delete-after`, but is not represented as authoritative rename detection
- Backups/versioning use `--backup` and `--backup-dir`
- SSH credentials are delegated to OpenSSH, `ssh-agent`, and the desktop key-management ecosystem
- Development is planned so that Microsoft Copilot can generate, modify, test, package, and deliver most repository artifacts directly; a local coding agent is not assumed

## 3. Scope

### 3.1 Version 1

- Profile creation, editing, cloning, import, and export
- Local and SSH endpoints
- Connectivity and capability checks
- Dry-run comparison
- Changed-only and all-objects views
- Tree and flat-list presentations
- Configurable metadata columns
- Per-object and per-subtree action controls
- Ordered rsync include/exclude filters
- Safe brace convenience expansion
- Backup/versioning modes
- Optional `--fuzzy --delete-after`
- Transfer progress, throughput, ETA, current object, summary, and logs
- Local path browsing
- SSH path browsing, with manual path entry always available
- Cancellation and failure recovery guidance
- Packaging for Linux

### 3.2 Deferred

- Bidirectional synchronization
- Persistent two-sided conflict history
- Guaranteed rename/move detection
- Rsync daemon endpoints
- Cloud APIs
- Embedded rsync or private rsync protocol implementation
- Windows as a first-class target
- Arbitrary regular-expression filters
- Remote-to-remote copies

## 4. Synchronization model

### 4.1 Direction

```text
Source -> Destination
```

The UI makes direction visually unambiguous. A deliberate Swap action invalidates the active comparison plan.

### 4.2 Global policy

For an existing destination object that would be changed or replaced:

- **Override:** select the rsync-proposed action; this is the default
- **Skip:** protect the object from the run
- **Unselect:** show it unchecked until the user selects it

In v1, “conflict” is a UI policy term. It is not a historical three-way conflict because qpy-rsync does not maintain a bidirectional state database.

### 4.3 Per-object actions

Each actionable row supports:

- Use global policy
- Execute proposed action
- Skip/protect

Directories use tri-state selection and can propagate a decision to descendants.

Rsync cannot consume an arbitrary transactional action graph directly. qpy-rsync therefore converts user decisions into an ordered temporary rsync filter file. Destination-only objects that are deselected must be protected explicitly when deletion is enabled.

Before transfer, qpy-rsync runs a second validation dry-run using the generated filters. If its normalized action set differs from the visible selected plan, execution is blocked and the discrepancy is shown.

### 4.4 Plan freshness

A plan records:

- profile and option fingerprint
- endpoint fingerprint
- comparison time
- local and remote rsync versions
- generated filter fingerprint

Validation immediately before execution is the default and recommended behavior.

## 5. Comparison and UI model

### 5.1 Dry-run contract

The backend uses an argument-vector equivalent of:

```text
rsync --dry-run --itemize-changes --out-format=<controlled-record> [OPTIONS] SOURCE DESTINATION
```

Requirements:

- set `LC_ALL=C`
- keep stdout and stderr separate
- parse only qpy-rsync's requested record format
- reject malformed records instead of guessing
- retain the raw itemized-change code
- verify supported rsync versions
- maintain parser fixtures for supported versions
- detect filenames that cannot be represented unambiguously by the selected output framing

The output parser is treated as a versioned internal protocol boundary.

### 5.2 Views

- **Changed only**, default
- **All objects**, loaded lazily
- **Tree view**, organized by relative path
- **Flat view**, sortable and filterable

Use `QAbstractItemModel`, not one widget per file. Large result sets must not be fully materialized as individual widgets.

### 5.3 Columns

Default:

- Selected
- Action
- Relative path
- Type
- Source size
- Destination size
- Source modification time
- Destination modification time

Optional:

- Source/destination permissions
- Owner and group where available
- Symlink target
- Raw itemized code
- Reason for action
- Estimated logical transfer size

### 5.4 Normalized actions

- Create file/directory/symlink
- Update content
- Update size/time
- Update metadata only
- Replace object type
- Delete destination object
- Skip/protect
- Unchanged
- Error/unsupported

## 6. Rename and move optimization

qpy-rsync exposes an optional **Fuzzy rename optimization** using:

```text
--fuzzy --delete-after
```

This can let rsync use a destination file due for deletion as a basis for a similarly named incoming file in the same directory, reducing transferred bytes.

It is not true rename detection:

- rsync reports an incoming transfer and a deletion, not a rename
- matching is heuristic
- same-directory cases are the useful baseline
- cross-directory moves are not reliably recognized
- destination space may temporarily be required for both objects

The v1 UI shows the two native actions. It may add a clearly non-authoritative “possible rename pair” annotation later, but such presentation must not alter transfer semantics.

## 7. Backups and versioning

Backups use one optional user-managed destination-side directory. An empty field
disables backups. A non-empty field backs up destination objects that rsync
alters or removes, without distinguishing overwrite, replacement, or deletion
reasons.

Implementation always pairs:

```text
--backup
--backup-dir=PATH
```

Plain `--backup` without `--backup-dir` is not exposed. Users control directory
naming, reuse, rotation, retention, and cleanup. Reusing a non-empty directory
is allowed with a warning that newer backups may replace older files with the
same relative path.

The path is interpreted on the destination side. SSH destinations therefore use
a remote filesystem path without `[user@]host:` syntax. Local paths expand `~`.
Filesystem root is rejected; the whole home directory, relative paths, nesting,
containment, and `--inplace` produce warnings as appropriate.

When the backup directory is nested inside source or destination, qpy-rsync
automatically injects an explicit protect/exclude pair before user filters:

```text
P /relative-backup-path/***
- /relative-backup-path/***
```

Protection can be disabled explicitly with a prominent warning. Local directory
inspection reports missing, empty, non-empty, and unavailable states. Remote
contents remain unchecked until a controlled SSH probe is implemented. Backup
setting changes invalidate the active comparison while retaining the old tree
for inspection.
## 8. Endpoints and transport

### 8.1 Endpoint types

- Local path
- SSH path: `[user@]host:/path`

### 8.2 Supported combinations

- Local -> Local
- Local -> SSH
- SSH -> Local

Not supported: SSH -> SSH in one operation.

### 8.3 Capability checks

A centralized capability service checks:

- local `rsync --version`
- remote `rsync --version`
- SSH connectivity
- remote rsync availability
- destination accessibility/writability where safely testable
- option compatibility

Metadata behavior can depend on both rsync versions, privileges, filesystems, ACL/xattr support, and mount options. qpy-rsync reports capabilities rather than assuming them.

## 9. Remote browsing and credentials

### 9.1 Local browsing

Use Qt filesystem APIs, preserving permission-error and symlink information.

### 9.2 SSH browsing

Rsync is not used as a general browser. Implement a separate `SshBrowser` behind an `EndpointBrowser` interface. Candidate implementation:

- OpenSSH `sftp` batch listing for broad compatibility
- controlled SSH helper commands only when output can be framed safely
- manual remote path entry at all times

### 9.3 Authentication

qpy-rsync does not store passwords or private keys in profiles. Preferred resolution order:

1. `~/.ssh/config`
2. public-key authentication
3. existing `ssh-agent`
4. KDE Plasma/KWallet or another desktop mechanism that unlocks keys into an agent
5. controlled askpass/terminal handoff when interactive authentication is required

OpenSSH remains responsible for host aliases, ports, identity files, `ProxyJump`, host-key verification, and agents.

## 10. Filters

The canonical model is rsync's ordered filter language. qpy-rsync presents one
ordered list with three rule types:

- **Include**, emitted as `--include=PATTERN`
- **Exclude**, emitted as `--exclude=PATTERN`
- **Advanced**, emitted as `--filter RULE`

The classic options are the preferred interface for ordinary migration from raw
rsync and other synchronizers. Advanced rules expose native rsync filter
features. All three types participate in the same ordered first-match rule list.

Rules retain an enabled state, type, pattern or native rule, optional comment,
and order. Disabled rules are persisted but omitted from the command vector.
The editor supports creation, editing, duplication, removal, reordering,
import, and export. Imported native filter-file lines become Advanced rules;
export writes enabled rules in native filter-file syntax.

Example using classic rules:

```text
Include  /.git/
Include  /.git/HEAD
Exclude  /.git/***
```

Parent traversal is significant. An included descendant is not discovered when
an earlier exclusion prevents rsync from descending through its parent. The UI
documentation therefore shows required parent-directory include rules for
include-only patterns.

Changing persistent rules invalidates the active comparison. qpy-rsync retains
the old tree with a visible stale marker, locks per-object decisions, and
requires a successful new dry-run before execution planning. A per-object
checkbox cannot re-include an object removed by persistent filters.

### 10.1 Brace convenience expansion

An expression such as:

```text
dir1/file{0,1}*
```

may be expanded by qpy-rsync into two native rules. The expansion is previewed, capped at 1,000 generated rules, and never delegated to a shell.

### 10.2 Regex

Arbitrary regex is deferred. Rsync filters are not regular expressions, and an unreliable translation would create dangerous mismatches between preview and execution.

### 10.3 Delete interaction

The UI distinguishes:

- excluded and protected from deletion
- excluded from transfer but eligible for deletion

The safe default is protected.

## 11. Required rsync options

The profile editor must support:

| Option | Meaning and UI warning |
|---|---|
| `--copy-links` | Copy link targets; may traverse outside the apparent tree |
| `--whole-file` | Disable delta transfer; useful for local copies or some fast LAN cases |
| `--relative` | Preserve source path structure; source spelling and `/./` matter |
| `--no-compress` | Explicitly disable compression where a preset enabled it |
| `--inplace` | Modify files in place; weaker interruption safety and special backup interactions |
| `--delete` | Remove destination-only objects; destructive |
| `--numeric-ids` | Preserve numeric IDs; identities may not map meaningfully |
| `--one-file-system` | Do not descend into additional mounted filesystems |
| `--sparse` | Recreate sparse files where possible |
| `--ignore-times` | Transfer all files regardless of quick-check results |

Delete timing choices:

- Before
- During
- Delay
- After

Enabling fuzzy rename optimization selects `--delete-after` unless the user explicitly disables optimization.

A centralized compatibility validator emits errors, warnings, and informational consequences for unsafe or contradictory combinations.

## 12. Profiles and persistent settings

Profiles are versioned JSON containing:

- UUID, name, and description
- source and destination endpoints
- preservation options
- filters
- global policy
- backup configuration
- fuzzy optimization
- delete setting/timing
- optional UI preferences
- non-secret history

Use `QStandardPaths.AppConfigLocation`, atomic writes, and schema migrations. Suggested layout:

```text
~/.config/qpy-rsync/
  profiles/
  settings.json
  logs/
  cache/
```

No passwords, passphrases, or private-key material are stored in profile JSON.

## 13. Progress, estimates, logs, and cancellation

Use `QProcess` with incremental stdout/stderr handling. Relevant rsync features include:

- `--info=progress2`
- `--stats`
- a controlled `--out-format`

Display:

- overall percentage where meaningful
- logical bytes processed/transferred
- current and smoothed throughput
- ETA
- item count
- current object
- deletion and metadata-operation counts
- final rsync exit code and summary

UI rendering is coalesced to about 5 to 10 updates per second. Parsing may continue at full input speed.

Cancellation:

1. request graceful termination
2. wait for a defined timeout
3. offer force termination
4. retain logs and mark the run incomplete
5. explain possible partial-file state, especially with `--inplace`

## 14. Architecture

```text
qpy-rsync/
  README.md
  LICENSE
  pyproject.toml
  docs/
    specification.md
    architecture.md
    rsync-output-contract.md
    security.md
    development-workflow.md
  src/
    qpy_rsync/
      __init__.py
      app.py
      gui/
        main_window.py
        compare_view.py
        profile_editor.py
        progress_view.py
        remote_browser.py
        dialogs.py
      core/
        models.py
        enums.py
        actions.py
        validation.py
        capabilities.py
      backend/
        rsync_process.py
        rsync_command.py
        rsync_parser.py
        rsync_filters.py
        rsync_probe.py
        ssh_process.py
        endpoint_browser.py
      storage/
        profile_store.py
        settings_store.py
        migrations.py
        log_store.py
      services/
        compare_service.py
        sync_service.py
        plan_validation_service.py
        credential_service.py
      resources/
  tests/
    unit/
    integration/
    fixtures/
      rsync_output/
  tools/
  packaging/
```

Layer rules:

- `gui`: presentation only
- `core`: transport-independent models and validation
- `backend`: process invocation, parsing, probes, and filter generation
- `storage`: profiles, settings, migrations, cache, and logs
- `services`: workflows coordinating the other layers

## 15. Copilot-first development workflow

The project will not assume regular access to a local coding agent. Microsoft Copilot should perform as much implementation work as the available environment permits.

### 15.1 Work Copilot can deliver directly

For each milestone, Copilot can generate and return downloadable artifacts such as:

- complete source files and package trees
- `pyproject.toml` and dependency configuration
- unit and integration tests
- test fixtures that can be generated locally without private systems
- developer documentation
- packaging scripts and CI configuration
- review patches or replacement files based on pasted errors/diffs
- release archives when requested

Copilot can execute tests and static checks in its sandbox when dependencies and system behavior are available there. It can also build repository snapshots as `.zip` or `.tar.gz` files for the user to unpack or commit.

### 15.2 Information the user may need to relay

Some checks necessarily occur on the user's actual Linux/KDE/SSH environment. The user can paste or attach when available:

- command output and tracebacks
- `git diff` or selected source files
- `rsync --version`, `ssh -V`, and platform/package versions
- raw dry-run/progress output with sensitive host/path data redacted
- screenshots for visual defects
- integration-test logs from real SSH hosts

The workflow must minimize this burden. Diagnostics should offer a **Copy diagnostic report** action that collects non-secret versions, profile semantics, executed argument vectors, exit codes, and redacted logs.

### 15.3 Iteration unit

Use small, self-contained increments:

1. Copilot produces a complete repository snapshot or patch for one milestone.
2. Copilot validates what can be validated in the sandbox.
3. The user runs one documented local smoke-test command or launches the app.
4. The user returns only failing output or a diff, if any.
5. Copilot produces corrected files or the next snapshot.

Avoid instructions that require the user to manually assemble many code fragments.

### 15.4 Source-control handoff

Because direct write access to the user's repository is not assumed, each delivery should contain:

- a full repository snapshot for major milestones, or a clearly scoped patch plus replacement files
- `CHANGELOG.md` entry
- exact test commands
- migration notes
- a short commit-message suggestion

The user remains the final party who pushes commits to the remote repository unless a connected repository tool becomes available.

## 16. Implementation milestones

### Milestone 0: Bootstrap and contracts, 1 to 2 days

- repository/package tree
- `pyproject.toml`
- application ID and license decision
- dataclasses/enums
- command builder
- supported version policy
- initial parser fixtures
- threat model
- basic CLI harness

**Exit:** command generation and profile validation work without launching the GUI.

### Milestone 1: Local compare prototype, 3 to 5 days

- `QProcess` wrapper
- local dry-run
- itemized parser
- scalable Qt model
- changed-only tree/flat view
- command/log display
- parser and command tests

**Exit:** reliable local comparison, including ordinary paths with spaces and shell metacharacters.

### Milestone 2: Selection and safe execution, 4 to 7 days

- policies and tri-state selection
- temporary filter generation
- validation dry-run
- actual local sync
- delete confirmations
- cancellation

**Exit:** selected changes run, deselected paths are protected, and plan mismatches are blocked.

### Milestone 3: Profiles and SSH, 4 to 7 days

- versioned profile store
- endpoint editor
- SSH aliases and agent authentication
- local-to-SSH and SSH-to-local
- capability probes and connection tests
- import/export without secrets

**Exit:** saved SSH profiles operate without qpy-rsync storing credentials.

### Milestone 4: Progress and summaries, 3 to 5 days

- progress2/stats parsing
- percentage, throughput, ETA, current path, counts
- throttled UI updates
- structured logs and final summary

**Exit:** long transfers remain responsive and auditable.

### Milestone 5: Filters, backups, and expert options, 5 to 8 days

- ordered rsync filters
- brace expansion
- backup/versioning modes
- required advanced options
- option compatibility validation
- fuzzy optimization preset

**Exit:** agreed options are expressible without arbitrary command injection.

### Milestone 6: Browsing and all-objects view, 4 to 8 days

- local browser
- SSH browser
- lazy all-objects view
- optional metadata columns and batched retrieval

**Exit:** common paths can be selected visually, with manual entry retained.

### Milestone 7: Packaging and hardening, 4 to 7 days

- wheel and at least one Linux distribution strategy
- local/SSH integration matrix
- accessibility and keyboard review
- large-tree performance tests
- recovery documentation

**Exit:** alpha release suitable for real data with prominent backup guidance.

### Estimated effort

- local-only proof of concept: about 1 week
- useful local/SSH alpha: about 3 to 5 focused weeks
- polished tested desktop release: about 2 to 3 months

These estimates are for implementation effort, not elapsed chat time. They assume iterative delivery and real-system smoke tests by the user for KDE/SSH-specific behavior.

## 17. Testing strategy

Unit tests:

- command argument vectors
- profile schema/migrations
- itemized parser
- deletion parser
- filter order/escaping
- selection-to-filter translation
- option compatibility
- progress parser

Integration tests:

- executable-bit-only changes
- nanosecond timestamp differences
- symlinks and link-target changes
- hard links
- ACLs and xattrs where supported
- sparse files
- type replacement
- deletion with excluded/protected objects
- interrupted transfer
- fuzzy basis reuse
- backup-directory layout
- local and SSH modes

Filename fixtures include spaces, tabs, leading dashes, quotes, wildcard characters, and non-ASCII text. Any unsupported newline/framing case must be detected and reported safely.

Performance cases:

- 100,000 unchanged objects
- 100,000 mixed changes
- deeply nested directories
- large delta transfer
- high-volume progress records

## 18. Security and reliability

- never invoke a shell for rsync or SSH
- pass argument lists to `QProcess`
- treat paths, endpoints, and filters as untrusted input
- prevent path values from being interpreted as options
- redact secrets and sensitive environment values from logs
- keep SSH host-key verification enabled
- use private temporary filter files and remove them after use
- write profiles atomically
- map rsync exit codes to actionable messages
- do not automatically retry destructive operations
- recommend backup mode or destination snapshots for early releases

## 19. Open decisions

1. Reverse-DNS application ID, suggested temporary value: `io.github.qpyrsync.qpyrsync`
2. License
3. Minimum tested rsync version
4. Whether every sync requires a visible compare step
5. Default delete setting, recommended off for new profiles
6. Default preservation preset
7. Initial packaging target
8. Whether expert free-form rsync arguments are allowed; recommendation: defer until visual-plan fidelity rules are defined

## 20. Primary technical reference

- rsync manual: <https://download.samba.org/pub/rsync/rsync.1>

The installed `rsync --version`, local/remote capability probes, and corresponding manual are authoritative for behavior on a user's system.
