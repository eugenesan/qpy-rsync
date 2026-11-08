# Architecture

`qpy-rsync` separates presentation, workflow, backend process control, domain models, and storage. The GUI never handles file contents. All rsync and SSH calls must use argument vectors through `QProcess`, never a shell.

The dry-run plan is ephemeral. User selections are later translated into a private temporary filter file and validated with a second dry-run before execution.
