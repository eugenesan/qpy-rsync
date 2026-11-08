# milestone 1 local smoke test

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Ensure `rsync` is installed, then create a safe test pair:

```bash
rm -rf /tmp/qpy-rsync-source /tmp/qpy-rsync-destination
mkdir -p /tmp/qpy-rsync-source/sub /tmp/qpy-rsync-destination
printf 'new\n' > /tmp/qpy-rsync-source/new.txt
printf 'changed-new\n' > /tmp/qpy-rsync-source/changed.txt
printf 'changed-old\n' > /tmp/qpy-rsync-destination/changed.txt
printf 'destination-only\n' > /tmp/qpy-rsync-destination/old.txt
chmod 755 /tmp/qpy-rsync-source/new.txt
qpy-rsync
```

In the GUI select the two directories, preserving the trailing slash, and click **Compare**. This milestone performs only `rsync --dry-run`; it does not synchronize or delete data. Because deletion is off in the ad-hoc profile, `old.txt` is not expected in the result yet.

Expected visible changes include `new.txt`, `changed.txt`, and `sub/`. The lower pane shows the exact display form of the argument vector and any rsync diagnostics.

## Current limitations

- Local endpoints only in the milestone 1 UI.
- Changed-only flat table; hierarchical and all-objects views come later.
- No per-item selection and no real synchronization.
- The output parser rejects malformed controlled records. POSIX filenames containing newlines remain an explicitly unsupported edge case until binary-safe framing is implemented.
