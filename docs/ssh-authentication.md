# SSH authentication

qpy-rsync delegates authentication to OpenSSH. For remote comparisons it sets:

```text
SSH_ASKPASS=/path/to/discovered/helper
SSH_ASKPASS_REQUIRE=force
```

`SSH_ASKPASS_REQUIRE=force` is supported by OpenSSH 8.4 and later and makes SSH use the graphical helper for password and key-passphrase requests even when terminal detection would otherwise choose a TTY.

Discovery order:

1. executable path already set in `SSH_ASKPASS`
2. `ksshaskpass`
3. `ssh-askpass`
4. `ssh-askpass-gnome`
5. `gnome-ssh-askpass`

For KDE Plasma, install the distribution's `ksshaskpass` package. The helper can integrate with KWallet depending on desktop configuration. Key-based authentication through `ssh-agent` remains preferred because it avoids repeated password prompts.

Examples:

```bash
export SSH_ASKPASS=/usr/bin/ksshaskpass
qpy-rsync
```

If no helper is found, qpy-rsync blocks the remote operation and displays an installation/configuration message instead of allowing rsync to hang.

A changed host key remains a hard failure. qpy-rsync does not bypass OpenSSH host-key verification.
