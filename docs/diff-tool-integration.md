# External diff-tool integration design

## Goal

Allow the user to open a selected changed regular file in an external visual
diff tool without moving SSH credential handling into qpy-rsync.

## Tool selection

qpy-rsync should follow Git's familiar diff-tool selection conventions while
launching tools directly for arbitrary filesystem endpoints.

Selection precedence:

1. Per-profile qpy-rsync diff-tool override
2. Git `diff.guitool`
3. Git `diff.tool`
4. First installed supported GUI tool

Initial supported tools:

- meld
- kdiff3
- kompare
- vimdiff

Resolve Git configuration with argument-vector subprocess calls:

```text
git config --get diff.guitool
git config --get diff.tool
git config --get difftool.<tool>.path
```

`difftool.<tool>.cmd` contains shell syntax and `$LOCAL`/`$REMOTE`
substitutions. Support for arbitrary configured commands is deferred until the
security and quoting model is explicit.

## File preparation

Local-to-local comparisons launch both paths directly.

For one SSH endpoint, copy the remote file to a private temporary directory
before launching the diff tool. Use:

```text
$XDG_RUNTIME_DIR/qpy-rsync/diff/<random-id>/
```

Requirements:

- directory mode `0700`
- preserve the relative filename where practical
- launch detached from the main GUI
- clean stale directories at the next application start
- never include passwords or private-key material

The first implementation supports changed regular files only. Disable the
command for directories, sockets, devices, and other special objects. For a
one-sided regular file, defer comparison against an empty file until the normal
two-sided path is stable.

## UI behavior

- Context-menu action: **Open in Diff Tool**
- Double-click a comparable changed regular file
- Toolbar action enabled only when one comparable regular file is selected
- Clear error when no supported tool is configured or installed
- Status/log entry showing the selected tool and relative path

Use `QProcess.startDetached()` for the external tool so qpy-rsync remains
responsive and the tool survives independently.

## Safety

- Build argument vectors; do not concatenate a shell command.
- Validate that both prepared paths are regular files.
- Do not follow special-file endpoints into devices or sockets.
- Do not execute arbitrary `difftool.<tool>.cmd` in the initial milestone.
- Treat endpoint paths as data, including names that begin with `-`.
