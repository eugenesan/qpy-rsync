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

### Milestone 1.16: profiles and the Ubuntu packaging

- complete the profile persistence and the recent-profile handling
- install the desktop file, the icon, the documentation and the launcher
- build a Debian package on Ubuntu's system Python and PySide6
- declare the rsync, OpenSSH, util-linux and optional askpass dependencies
- add the package installation and the smoke tests

### After 1.16

- review the removal of the `/tmp/qpy-rsync-smoke` execution restriction
- harden the synchronization further and validate it on real trees
- refine the conflict policy of an existing destination object
- improve the rename and move detection
- extend the external tools with a per-tool working directory and a
  per-profile selection
