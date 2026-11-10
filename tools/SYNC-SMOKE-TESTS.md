# Guided synchronization smoke tests

The guided runner tests real synchronization only inside `/tmp/qpy-rsync-smoke`.
It recreates the fixture before every case, launches the normal GUI with startup
arguments, prints exact manual steps, collects filesystem inventories and logs,
and copies the final report through `dump-content.sh`.

## Test matrix

Run each command independently. Close the GUI only after synchronization and
the automatic post-sync comparison finish.

```bash
./tools/run-sync-smoke-test.sh update default
./tools/run-sync-smoke-test.sh update manual-delete
./tools/run-sync-smoke-test.sh mirror default
./tools/run-sync-smoke-test.sh mirror protect-one
./tools/run-sync-smoke-test.sh new-only default
./tools/run-sync-smoke-test.sh new-only manual-delete
./tools/run-sync-smoke-test.sh update cancel
./tools/run-sync-smoke-test.sh update failure
```

Each invocation resets the fixture. Do not run two cases concurrently.

## Understanding the comparison trees

The Source and Destination trees are difference views, not filesystem browsers.
They display comparison results and selected synchronization actions rather than
complete directory contents.

After an automatic post-sync comparison:

- If comparison reports 0 remaining differences, both trees are expected to be
  empty. This indicates that no further actions are available.
- Update and New Only can intentionally leave differences because those modes
  retain some Destination content by default.
- Verify Selected Actions and Synchronize should be disabled when no actionable
  differences remain.

## What to paste back

`dump-content.sh` copies the generated report in one or more packed clipboard
batches. Paste every batch in order. The report contains:

- selected mode and case
- application exit status
- Git commit and working-tree status
- exact Source, Destination, and Backup inventories
- SHA-256 hashes of all test files
- key Destination file contents
- GUI process stdout/stderr
- the tail of `/tmp/qpy-rsync.log`

## Cancellation and failure cases

Run these only after the six normal mode cases pass.

- update cancel: cancel an active synchronization and verify STATE synchronization-cancelled.
- update failure: intentionally break the Source path after verification and verify STATE synchronization-failed.

## Safety

The current `SyncService` rejects write-capable execution unless local Source,
Destination, and any Backup path are below `/tmp/qpy-rsync-smoke/`.
