# Development roadmap

The roadmap follows the comparison-first safety model. Each milestone must
preserve the full Git history, pass the complete test suite, compile the Python
sources, and be delivered as a Git-generated downloadable patch.

## Completed foundation

Milestones 1 through 1.10 established:

- asynchronous rsync dry-run comparison
- controlled output parsing and diagnostics
- destination-only inventory
- synchronized hierarchical source/action/destination views
- local and SSH endpoint parsing
- graphical OpenSSH askpass support
- system-process environment sanitization
- restoration of X11 `DISPLAY` for rsync's SSH remote shell

## Milestone 1.11: installation and development documentation

- make `.venv` explicitly optional
- document Ubuntu system-Python/PySide6 setup
- document runtime and development packages separately
- document `qpy-rsync.sh`
- document system-Python tests for the repository's `src/` layout
- document current SSH and debugging prerequisites
- record the external diff-tool design and revised roadmap

## Milestone 1.12: external diff tool

- resolve a preferred tool using Git-compatible selection conventions
- support meld, kdiff3, kompare, and vimdiff
- add **Open in Diff Tool** for one selected changed regular file
- launch local-to-local comparisons directly
- stage one remote file privately for local-to-SSH comparisons
- disable unsupported object types with an actionable explanation
- defer arbitrary `difftool.<tool>.cmd` shell expressions

## Milestone 1.13: comparison-tree usability (completed)

- ancestor-preserving filename filtering
- shell-style glob matching and directory-subtree mode
- synchronized expand/collapse controls
- corrected destination-tree rendering and responsive columns
- persisted window, splitter, and header geometry
- persisted endpoint pair and Enter-to-compare workflow

File-type icons and additional accessible action styling remain candidates for
a later usability refinement.

## Milestone 1.14: per-object decisions

- include/exclude state per changed object
- inherited directory selection
- action controls in the center gutter
- conflict-policy visualization
- validation of impossible or stale selections
- invalidate selections safely after recompare

## Milestone 1.15: synchronization execution

- generate an execution plan from validated selections
- show a final confirmation summary
- perform real rsync execution
- parse progress and statistics
- support cancellation and exit-code mapping
- recompare after completion
- add explicit destructive-action guardrails

## Milestone 1.16: profiles and Ubuntu packaging

- complete profile persistence and recent-profile handling
- install desktop file, icon, documentation, and launcher
- build a Debian package using Ubuntu's system Python and PySide6
- declare rsync, OpenSSH, util-linux, and optional askpass dependencies
- add package installation and smoke tests

## Delivery gate

Before any milestone patch is delivered:

```bash
git apply --check milestone.patch
git apply milestone.patch
git diff --check
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest -q
/usr/bin/python3 -m compileall -q src
```

When a milestone changes runtime behavior, its patch also requires a focused
manual smoke test documented in the milestone notes.
