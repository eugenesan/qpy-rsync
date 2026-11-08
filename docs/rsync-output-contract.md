# Rsync output contract

Comparison uses `--dry-run`, `--itemize-changes`, `LC_ALL=C`, and a controlled `--out-format`. The parser will retain raw itemized codes and reject malformed records. Output framing and filename edge cases must be covered by fixtures before transfer execution is enabled.
