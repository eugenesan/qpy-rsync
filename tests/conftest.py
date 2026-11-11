from __future__ import annotations

import os
import tempfile

# Keep QSettings and session-log state out of the developer's real XDG state
# directory while the test suite runs.
os.environ.setdefault(
    "XDG_STATE_HOME", tempfile.mkdtemp(prefix="qpy-rsync-test-state-")
)
