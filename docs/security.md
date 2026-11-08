# Security baseline

- Never use `shell=True` or concatenate a command for execution.
- Keep SSH host-key verification enabled.
- Do not store passwords, passphrases, or private keys.
- Redact environment values and credentials from diagnostics.
- Use private temporary filter files.
- Require validation before destructive execution.
- Treat `--delete`, `--inplace`, and `--copy-links` as high-visibility options.
