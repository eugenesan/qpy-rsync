# Repository and delivery policy

- The working representation is a Git repository with `main` as its default branch.
- Every completed implementation increment is committed before delivery.
- Release tarballs include the complete `.git` directory, branches, tags, and commit history.
- Generated caches, virtual environments, build outputs, and secrets remain excluded.
- Each delivery reports the included commit ID and verifies that the archive's Git worktree is clean.
