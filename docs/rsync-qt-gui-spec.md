# Rsync Qt GUI: Product Specification and Implementation Plan

**Status:** Initial specification, v0.1  
**Target platform:** Linux desktop, with KDE Plasma as a primary environment  
**UI toolkit:** Python 3 and PySide6  
**Synchronization backend:** External `rsync` executable  
**Initial scope:** One-way synchronization, local and remote endpoints, dry-run preview, per-item action control, progress reporting, profiles, SSH-based authentication

## 1. Product vision

Build a modern graphical frontend for `rsync` that combines:

- rsync's POSIX metadata fidelity and mature transfer engine
- a FreeFileSync-like visual comparison tree
- a mandatory or strongly encouraged dry-run preview
- per-object control over proposed actions
- reusable profiles and native SSH credential handling
- transparent display of the exact command and logs

The application is a visualization, configuration, and control layer. It does not implement its own file-copying or delta-transfer engine. `rsync` remains the source of truth for both preview and execution.

## 2. Core design principles

1. **Preview and execution must use the same backend and equivalent options.**
2. **The GUI must not process file data.** It launches and monitors `rsync`; file data flows through `rsync` and, where applicable, SSH.
3. **Arguments are always passed as an argument vector.** Never construct a shell command string and never rely on shell expansion.
4. **Passwords are not stored in profiles.** Authentication uses OpenSSH configuration, keys, `ssh-agent`, KWallet integration supplied by the desktop, or an optional system keyring adapter later.
5. **Potentially destructive operations are explicit.** Deletions, overwrites, `--inplace`, and `--delete` receive clear UI treatment.
6. **The generated command is inspectable.** The UI shows a safely quoted display form, rsync version, endpoint type, and relevant environment information.
7. **Per-item overrides must be faithfully translated into rsync filters or protected-path rules.** If the GUI cannot express the requested plan without changing semantics, execution is blocked with an explanation.
8. **No hidden synchronization database in v1.** The dry-run result is an ephemeral plan, not a historical truth database.

## 3. Scope

### 3.1 Version 1 scope

- One-way source-to-destination synchronization
- Local-to-local, local-to-SSH, SSH-to-local
- Optional rsync daemon endpoints
- Saved profiles
- Dry-run comparison
- Changed-only and all-objects views
- Tree and flat-list presentations
- Optional metadata columns
- Per-object action toggles
- Exclusion and inclusion rules using rsync's native filter language
- Backup/versioning using `--backup` and `--backup-dir`
- Basic rename optimization using `--fuzzy --delete-after`
- Transfer progress, speed, ETA, current item, summary, and logs
- Remote browsing over SSH/SFTP-compatible OpenSSH tools
- Rsync daemon module listing
- Cancel and graceful termination
- Export/import of non-secret profile data

### 3.2 Explicitly deferred

- True bidirectional synchronization
- Conflict resolution based on a persistent two-sided history database
- Reliable semantic rename detection and rename reporting
- Cloud-provider APIs
- Embedded rsync or a private rsync protocol implementation
- Windows as a fully supported first-class platform
- Regex filters translated into an approximation of rsync filters
- Cross-remote synchronization, because rsync supports at most one remote endpoint per invocation

## 4. Terminology

- **Plan:** Parsed output of a dry-run for a specific profile and option set.
- **Action:** What rsync proposes for an object, such as create, update content, update metadata, delete, replace type, or no change.
- **Override:** Destination object will be replaced or updated according to source state.
- **Skip:** Object is protected from the planned transfer.
- **Unselected:** Object is shown but is not included until the user explicitly enables it.
- **Endpoint:** Local path, SSH path, or rsync daemon URL/module.
- **Conflict:** In v1, a UI policy term for an existing destination object that would be replaced or materially changed. It is not a historical three-way conflict.

## 5. Synchronization model

### 5.1 Direction

Version 1 supports one direction only:

```text
Source -> Destination
```

The UI must make direction visually unambiguous and provide a deliberate Swap button. Swapping endpoints invalidates any existing plan.

### 5.2 Global action policy

For objects that would overwrite, replace, or materially modify an existing destination object:

- **Override:** selected by default and passed through to rsync
- **Skip:** protected or excluded from execution
- **Unselect:** initially unchecked; the user must select each applicable object or subtree

The default global policy is **Override**.

### 5.3 Per-object action control

Every actionable row supports:

- Use global policy
- Execute proposed action
- Skip/protect

Directory-level toggles propagate to descendants, with a tri-state checkbox for mixed selections.

Important implementation constraint: rsync does not accept an arbitrary precomputed list of deletions and transfers as a transaction. The backend must generate a temporary, ordered filter file for the selected plan. Deletion protection must use rsync filter semantics carefully so deselected destination-only objects are not deleted by `--delete`.

Before execution, the application performs a lightweight validation dry-run using the generated filters. If the validated action set differs from the visible selected plan, execution is blocked and the differences are shown.

### 5.4 Plan freshness

A dry-run is a snapshot of changing filesystems. Before execution, the application records:

- profile/options fingerprint
- source and destination endpoint identity
- time of comparison
- rsync version
- generated filter fingerprint

Default behavior is to run the validation dry-run immediately before transfer. A profile may allow skipping this revalidation, but the UI must label it as unsafe.

## 6. Comparison and visual model

### 6.1 Dry-run command

The compare backend uses an argument-vector equivalent of:

```text
rsync --dry-run --itemize-changes --out-format=<machine record> [profile options] SOURCE DESTINATION
```

The exact record format must be versioned in code. Use an uncommon field separator and protect against filenames containing newlines. Rsync output is not a formal binary API, so the parser must:

- validate the installed rsync version
- use `LC_ALL=C`
- parse only explicitly requested `--out-format` records
- keep stderr separate
- reject malformed records rather than guessing
- include parser fixtures for supported rsync versions

If robust filename framing cannot be guaranteed for every possible POSIX filename, document the limitation, detect ambiguous output, and block execution for affected entries. A later helper process may provide binary-safe framing without embedding rsync.

### 6.2 Views

The main comparison area supports:

- **Changed only:** default view
- **All objects:** changed and unchanged objects
- **Tree view:** hierarchy by path
- **Flat view:** sortable list of actions

All-objects view may require an additional listing operation because a normal itemized dry-run primarily reports changed items. The UI should load unchanged objects lazily and avoid constructing millions of Qt items at once.

### 6.3 Columns

Default columns:

- Selected
- Action
- Relative path
- Object type
- Source size
- Destination size
- Source modified time
- Destination modified time

Optional columns:

- Source mode/permissions
- Destination mode/permissions
- Owner and group, where available
- Link target
- Itemized-change code
- Reason for action
- Estimated transfer size

Metadata availability depends on transport. Remote supplementary metadata may require batched `stat` calls or a remote helper and must not silently be invented.

### 6.4 Action categories

At minimum:

- Create file
- Create directory
- Create symlink
- Update content
- Update size/time
- Update metadata only
- Replace object type
- Delete destination object
- Skip/protect
- Unchanged
- Error or unsupported

The parser retains the raw rsync itemized code alongside the normalized action.

## 7. Rename and move optimization

### 7.1 Version 1 behavior

Version 1 may expose **Fuzzy rename optimization** as an optional profile feature implemented with:

```text
--fuzzy --delete-after
```

This can allow rsync to use a destination file scheduled for deletion as a basis file for a similarly named incoming file in the same directory, reducing transferred data. `--delete-after` preserves deletion candidates until transfers finish.

### 7.2 Limitations

This is not true rename detection:

- rsync still reports an incoming file and a deletion, not a rename operation
- matching is heuristic
- the useful basis file is generally expected in the destination directory
- cross-directory moves are not reliably detected
- the destination may temporarily require space for both objects
- `--fuzzy` may choose an imperfect basis but rsync still verifies/reconstructs the correct destination content

Therefore the UI will initially report the two native actions. It may add a non-authoritative **possible rename pair** annotation when source/destination paths, sizes, and checksums or strong metadata heuristics support it. Such pairing is presentation only and must never change rsync semantics.

### 7.3 Future enhancement

A future optional rename index may store path, size, mtime, inode where meaningful, and content hash. This would be a separate feature with clearly stated costs and would not be required for v1.

## 8. Backups and versioning

### 8.1 Modes

- None
- Back up overwritten objects
- Back up deleted objects
- Back up overwritten and deleted objects

Implementation uses rsync's:

```text
--backup
--backup-dir=PATH
```

The backup directory should be outside the active destination tree where possible. If it is inside, generated filters must prevent recursive synchronization of the backup tree.

### 8.2 Version layouts

Support:

1. **Single recovery tree:** latest displaced version at matching relative path
2. **Timestamped runs:** `BACKUP_ROOT/YYYY-MM-DD_HH-mm-ss/<relative-path>`
3. **Custom template:** later, with validated placeholders

Rsync recreates relative paths under `--backup-dir`, which provides the desired FreeFileSync-style recovery structure.

### 8.3 Safety checks

- Reject a backup path equal to source or destination.
- Warn if the backup path is nested under source or destination.
- Confirm available space where it can be estimated.
- Show backup behavior in the dry-run summary.

## 9. Endpoints and transport

### 9.1 Endpoint types

- Local path
- SSH remote-shell path: `[user@]host:/path`
- Rsync daemon module: `[user@]host::module/path`
- Rsync URL: `rsync://[user@]host[:port]/module/path`

Rsync behavior is mostly transparent to the GUI for compare and transfer, but capabilities differ. The profile validator must maintain a capability matrix.

### 9.2 Constraints

- Rsync cannot copy directly between two remote hosts in one invocation.
- ACL, xattr, owner, group, devices, hard links, timestamp precision, and numeric ID behavior depend on both rsync versions, privileges, protocol, and filesystems.
- SSH transport needs rsync installed on the remote host.
- Daemon mode may impose module-level read-only, authentication, filter, path, and option restrictions.
- Local and remote rsync versions may negotiate older protocol behavior.

### 9.3 Capability probe

For each endpoint/profile, collect where possible:

- local `rsync --version`
- remote `rsync --version` over SSH
- SSH connectivity
- destination writability
- supported rsync daemon module access
- optional ACL/xattr test in an explicit diagnostics workflow

Do not scatter probe commands through UI code. Implement them through backend capability services.

## 10. Filters and exclusions

### 10.1 Native filter model

The canonical filter representation is rsync's own ordered filter-rule language. UI modes:

- Simple excludes
- Simple includes
- Advanced ordered rsync rules
- Import/export filter file

Examples:

```text
- *.tmp
- /build/
+ /important/***
- *
```

Rule order matters and must be preserved.

### 10.2 Brace expressions

Shell brace syntax such as:

```text
dir1/file{0,1}*
```

is not passed to a shell. The UI may provide a deterministic convenience expander that converts it into separate rsync rules:

```text
dir1/file0*
dir1/file1*
```

Requirements:

- preview the expansion
- cap expansion count, initially 1,000 rules
- reject nested or malformed expressions in v1
- never use `shell=True`

### 10.3 Regex

Rsync filters are glob-like patterns, not general regular expressions. Version 1 will not pretend to translate arbitrary regex into rsync filters.

If regex support is later added, it must be a clearly separate preselection layer with exact documented semantics. It would likely require generating a file list and has complex interactions with directory traversal and deletion. It is deferred.

### 10.4 Deletion safety

With `--delete`, excluded and per-item skipped objects need explicit semantics:

- **Excluded from transfer but protected from deletion**
- **Excluded from transfer and eligible for deletion**

The UI must expose this distinction in advanced settings and choose the safer protected behavior by default.

## 11. Supported rsync options

### 11.1 Preservation defaults

Provide a clear preset rather than hiding everything behind `-a`:

- recursion
- symlinks as symlinks
- permissions
- modification times
- groups
- owners
- devices/specials where authorized
- optional hard links, ACLs, and xattrs

The command builder may emit `-a` plus explicit additions/removals, but the UI model stores individual semantic choices.

### 11.2 Required advanced options

| Option | UI label | Key warning or interaction |
|---|---|---|
| `--copy-links` | Copy symlink targets | Changes symlink semantics and can copy outside the apparent tree |
| `--whole-file` | Disable delta algorithm | Often useful for local copies or fast LAN storage |
| `--relative` | Preserve source path structure | Source argument spelling and `/./` placement affect results |
| `--no-compress` | Disable compression | Compression is normally off unless enabled; wording must reflect actual command |
| `--inplace` | Update destination files in place | Reduces atomicity and interacts with backup, snapshots, and interrupted transfers |
| `--delete` | Delete destination-only objects | Destructive; supports timing selection |
| `--numeric-ids` | Preserve numeric IDs | Useful for system trees; IDs may not map meaningfully on destination |
| `--one-file-system` | Do not cross filesystem boundaries | Mount points inside source are not traversed |
| `--sparse` | Create sparse destination files | Interacts with `--inplace`; validate supported combinations |
| `--ignore-times` | Transfer all files | Expensive; different from checksum comparison |

### 11.3 Delete timing

Expose:

- Before
- During
- Delay
- After

When fuzzy rename optimization is enabled, default to `--delete-after` and explain why.

### 11.4 Option compatibility layer

A centralized validator must detect dangerous or contradictory combinations before launching rsync. Validation severity:

- Error: cannot run
- Warning: runs but changes safety or performance
- Information: notable consequence

## 12. Remote discovery and browsing

### 12.1 Local browsing

Use Qt's filesystem facilities for local endpoints, with explicit handling of symlinks and permission errors.

### 12.2 SSH browsing

Rsync is not a full remote file browser. Use OpenSSH tooling:

- `sftp` batch commands for directory listing where practical
- or controlled `ssh` commands with machine-readable output from a small remote Python/shell helper when available

Initial implementation should use `sftp` or a conservative SSH listing adapter and treat browsing as optional. Users can always enter a remote path manually.

### 12.3 Rsync daemon modules

Module discovery can use a source-only invocation such as:

```text
rsync host::
```

or an `rsync://` URL without a destination, subject to daemon policy. The UI can display module names and comments, then list paths within an accessible module.

### 12.4 Browser abstraction

```text
EndpointBrowser
  LocalBrowser
  SshBrowser
  RsyncDaemonBrowser
```

Browsing and synchronization remain separate services.

## 13. Profiles, settings, and credentials

### 13.1 Profile contents

Profiles are versioned JSON documents containing:

- UUID, name, description
- source and destination endpoint definitions
- sync direction
- preservation options
- filter rules
- conflict policy
- backup/versioning configuration
- fuzzy optimization setting
- delete timing
- UI column/view preferences, optionally separate from sync semantics
- last-used timestamps and non-secret history

Profiles must never contain passwords or private-key material.

### 13.2 Storage paths

Use `QStandardPaths.AppConfigLocation`, expected to resolve to a path such as:

```text
~/.config/<application-id>/
```

Suggested layout:

```text
profiles/
settings.json
logs/
cache/
```

Use atomic writes and schema migrations.

### 13.3 SSH credentials

Preferred order:

1. OpenSSH configuration in `~/.ssh/config`
2. Public-key authentication
3. Existing `ssh-agent`
4. Desktop-provided key unlocking, such as KDE Wallet integration around the agent
5. Interactive terminal/askpass handoff where supported

The application should let OpenSSH resolve host aliases, ports, proxy jumps, identity files, host-key policy, and agents. Do not duplicate SSH configuration fields unnecessarily.

Provide a **Test connection** function that runs a noninteractive probe first and then allows an interactive authentication attempt through a controlled askpass/terminal flow.

## 14. Progress, estimates, cancellation, and logs

### 14.1 Process model

Use `QProcess`, not blocking `subprocess.run`, for compare and transfer operations. Keep stdout and stderr separate and process incrementally.

### 14.2 Progress sources

Use rsync features such as:

- `--info=progress2`
- `--stats`
- controlled `--out-format`

Show:

- overall percentage where meaningful
- transferred logical bytes
- current throughput and smoothed throughput
- ETA
- processed/total item counts
- current item
- deletion and metadata-operation counts

### 14.3 ETA limitations

ETA is approximate, especially for:

- many small files
- metadata-heavy trees
- fluctuating SSH links
- delta transfers where literal network bytes differ from logical file sizes
- receiver-side filesystem stalls

Display both logical progress and, when available, rsync's reported transfer statistics. Avoid claiming byte-perfect network usage.

### 14.4 UI throttling

Parse all records but coalesce visual updates to roughly 5 to 10 updates per second. Use a model rather than one widget per file, and avoid re-sorting the tree on every record.

### 14.5 Cancellation

Cancellation sequence:

1. Request graceful interruption of the local rsync process.
2. Allow a short timeout.
3. Offer force termination.
4. Preserve logs and mark the run incomplete.
5. Explain possible partial files and the effects of `--partial` or `--inplace`.

## 15. Architecture

```text
src/rsync_gui/
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
    icons/
  tests/
    unit/
    integration/
    fixtures/
```

### 15.1 Layer responsibilities

- **gui:** presentation and user interaction only
- **core:** transport-independent data models, validation, and normalized actions
- **backend:** exact process invocation, parsing, probing, and filter generation
- **storage:** profiles, settings, migrations, cache, and logs
- **services:** application workflows coordinating backend, models, and storage

### 15.2 Key interfaces

```python
class RsyncBackend:
    def build_compare_job(profile) -> ProcessSpec: ...
    def build_validation_job(profile, plan) -> ProcessSpec: ...
    def build_sync_job(profile, plan) -> ProcessSpec: ...
    def parse_compare_record(record: bytes) -> Change: ...

class ProfileStore:
    def list_profiles() -> list[ProfileSummary]: ...
    def load(profile_id: str) -> SyncProfile: ...
    def save(profile: SyncProfile) -> None: ...

class EndpointBrowser:
    def list(path: EndpointPath) -> list[RemoteEntry]: ...
```

## 16. Initial repository tree

```text
rsync-qt-gui/
  README.md
  LICENSE
  pyproject.toml
  docs/
    specification.md
    architecture.md
    rsync-output-contract.md
    security.md
  src/
    rsync_gui/
      __init__.py
      app.py
      gui/
      core/
      backend/
      storage/
      services/
      resources/
  tests/
    unit/
    integration/
    fixtures/
      rsync_output/
  tools/
  packaging/
```

This document should be stored as `docs/specification.md` in the repository.

## 17. Implementation plan

### Milestone 0: Repository and contracts, 1 to 2 days

- Create package layout and `pyproject.toml`
- Select application ID and license
- Define supported Python, PySide6, and rsync version ranges
- Add model dataclasses and enums
- Add command builder with argument-vector output
- Capture fixture output from representative rsync versions
- Write threat model for paths, filters, SSH arguments, logs, and destructive options

**Exit criterion:** a CLI test harness can build and print compare commands without launching the GUI.

### Milestone 1: Compare proof of concept, 3 to 5 days

- Implement `QProcess` wrapper
- Run local-to-local dry-runs
- Parse itemized records and deletions
- Populate a scalable `QAbstractItemModel`
- Implement changed-only view
- Show raw command and logs
- Add parser and command-generation tests

**Exit criterion:** local directory pairs can be compared reliably, including spaces and shell metacharacters in ordinary filenames.

### Milestone 2: Selection and safe execution, 4 to 7 days

- Implement global override/skip/unselect policy
- Implement tri-state per-item selection
- Generate temporary filter files
- Implement pre-execution validation dry-run
- Execute sync and compare observed actions with the validated plan
- Add delete safety confirmation and cancellation

**Exit criterion:** selected local changes execute, deselected objects are protected, and destructive mismatches are blocked.

### Milestone 3: Profiles and SSH, 4 to 7 days

- Add versioned JSON profile storage
- Add endpoint editor
- Respect OpenSSH aliases and agent authentication
- Add local-to-SSH and SSH-to-local compare/sync
- Add capability probes and connection tests
- Add profile import/export without secrets

**Exit criterion:** a saved SSH profile works without the application storing credentials.

### Milestone 4: Progress and summaries, 3 to 5 days

- Parse `--info=progress2` and stats
- Add progress bar, throughput, ETA, item counts, current path
- Throttle UI updates
- Store structured run logs and final summary

**Exit criterion:** long transfers remain responsive and produce a useful audit log.

### Milestone 5: Filters, backups, and advanced options, 5 to 8 days

- Add native ordered rsync filters
- Add brace convenience expansion
- Add backup/versioning modes
- Add required advanced options and compatibility validation
- Add fuzzy optimization preset using `--fuzzy --delete-after`
- Add option-level help and warnings

**Exit criterion:** profiles can express the agreed options without arbitrary free-form command injection.

### Milestone 6: Browsing and all-objects view, 5 to 10 days

- Add local browser
- Add SSH path browser
- Add rsync daemon module discovery
- Add lazy all-objects view
- Add optional metadata columns and batched metadata retrieval

**Exit criterion:** users can select common local and remote paths without manually typing them, while manual entry remains supported.

### Milestone 7: Packaging and hardening, 4 to 7 days

- Package for at least one target, preferably a Python wheel plus an Arch/Debian-friendly recipe or Flatpak evaluation
- Add integration test matrix for local, SSH, daemon, symlinks, permissions, ACLs, xattrs, sparse files, deletes, backup-dir, interruption, and version skew
- Add accessibility and keyboard navigation review
- Add large-tree performance tests
- Add recovery documentation

**Exit criterion:** an alpha release is suitable for real data with prominent backup recommendations.

### Estimated effort

- Narrow local-only proof of concept: roughly 1 week
- Useful local and SSH alpha: roughly 3 to 5 weeks of focused development
- Polished, well-tested desktop application: roughly 2 to 3 months, depending on remote browsing, packaging, and edge-case coverage

These estimates assume one experienced Python developer and reuse of the external rsync and OpenSSH executables.

## 18. Testing strategy

### 18.1 Unit tests

- command argument generation
- profile schema and migration
- itemized-change parser
- delete record parser
- filter ordering and escaping
- selection-to-filter translation
- option compatibility validation
- progress parser

### 18.2 Integration tests

Create temporary source/destination trees covering:

- regular files and directories
- executable-bit-only changes
- nanosecond timestamp differences
- symlinks and changed link targets
- hard links
- ACLs and xattrs
- sparse files
- object type replacement
- filenames with spaces, tabs, leading dashes, quotes, wildcard characters, and non-ASCII text
- deletion with excluded and protected objects
- interrupted transfer
- fuzzy basis reuse
- backup directory structure

Test local, SSH loopback/container, and rsync daemon modes separately.

### 18.3 Golden fixtures

Store raw stdout/stderr fixtures for each supported rsync major/minor family. Parser changes must be tested against all fixtures.

### 18.4 Performance tests

At minimum:

- 100,000 unchanged files
- 100,000 mixed changes
- deep directory tree
- large single file with delta transfer
- UI update throttling under high record rates

## 19. Security and reliability requirements

- Never invoke a shell for rsync/SSH commands.
- Treat endpoint strings, paths, and filter rules as untrusted input.
- Prevent options hidden inside path arguments by using proper positional handling and `--` where supported/appropriate.
- Redact secrets and sensitive environment variables from logs.
- Do not disable SSH host-key verification by default.
- Do not invent automatic retries for destructive operations.
- Write profiles atomically.
- Keep temporary filter files private and delete them after the job.
- Display rsync exit code and map known exit codes to actionable messages.
- Recommend destination snapshots or backup mode for first use.

## 20. Decisions captured in v0.1

- PySide6 is the UI toolkit.
- External rsync is the backend; no librsync and no embedded rsync fork.
- Version 1 is one-way.
- The default conflict policy is override, with skip and unselect alternatives.
- Every proposed action can be toggled manually, subject to plan validation.
- Changed-only and all-objects views are required.
- Metadata columns are user-configurable.
- Fuzzy rename optimization is included as an optional transfer optimization, not represented as authoritative rename detection.
- Rsync-native filters are canonical; regex is deferred.
- Backups use `--backup` and `--backup-dir`.
- SSH credentials are delegated to OpenSSH and the desktop agent/keyring ecosystem.
- Remote browsing is a separate adapter, not a responsibility of the synchronization engine.

## 21. Open decisions before implementation

1. Application name and reverse-DNS application ID
2. License, likely GPL-compatible because the application invokes rather than links to rsync, but dependencies and packaging still need review
3. Minimum tested rsync version
4. Whether compare is mandatory before every sync
5. Default delete behavior, recommended off for new profiles
6. Default archive/preservation preset
7. Whether all-objects view is in the alpha or follows the core compare/sync workflow
8. Initial packaging target: wheel, distro package, AppImage, or Flatpak
9. Whether free-form extra rsync arguments are allowed; recommendation is expert-only with strong warnings and no guarantee of visual plan fidelity

## 22. Primary technical reference

- [rsync manual](https://download.samba.org/pub/rsync/rsync.1)

The implementation should treat the installed `rsync --version` and corresponding manual as authoritative for behavior on a user's system.
