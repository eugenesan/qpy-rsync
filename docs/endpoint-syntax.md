# Endpoint syntax

Both Source and Destination accept the same syntax.

## Local

```text
/home/alice/data
~/data
```

`~` is expanded by qpy-rsync. Directory entries are normalized to trailing-slash semantics, so `/data/project` means “the contents of project”, equivalent to the rsync operand `/data/project/`.

## SSH

```text
server:/srv/data
alice@server:/srv/data
nas-alias:/backup/documents
```

This is rsync's remote-shell syntax, not a URL. `nas-alias` may be a `Host` alias from `~/.ssh/config`, including its configured `User`, `Port`, `IdentityFile`, or `ProxyJump`. Authentication is handled by OpenSSH and the active `ssh-agent`/desktop key manager.

Constraints:

- the remote path must be absolute, beginning with `/`, or begin with `~/`
- at most one side may be remote
- `host::module` and `rsync://` daemon syntax are not supported
- IPv6 literal syntax is not implemented yet

Examples:

```text
Source:      /home/alice/Documents
Destination: alice@nas:/volume1/backups/Documents
```

```text
Source:      buildbox:/srv/releases
Destination: ~/Downloads/releases
```
