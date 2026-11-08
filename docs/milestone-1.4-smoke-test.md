# milestone 1.4 smoke test

Run:

```bash
pytest
QPY_RSYNC_DEBUG=1 qpy-rsync
```

Compare the same trees used for milestone 1.3. Verify:

- source, action, and destination panes are visible
- directory expansion, collapse, selection, and vertical scrolling stay synchronized
- source-only rows have an empty destination peer and `create` action
- destination-only rows have an empty source peer and `keep` action while deletion is disabled
- destination-only files/directories no longer show `Unknown`, size `0`, or an epoch timestamp
- a local path beginning with `~/` is expanded to the current home directory

The panes currently show rsync's source-side metadata where available. Rsync deletion records do not contain real destination size/time metadata, so those cells remain blank until the later endpoint metadata scanner is implemented.
