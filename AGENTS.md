# AGENTS

This file applies to the entire repository.

## Development workflow
1. Keep shell scripts POSIX-compliant (`/bin/sh`) and run `shellcheck` locally when practical.
2. Format Swift sources with `swift-format` if available.
3. Exercise the installer on macOS before publishing changes.

When updating launch agent templates, ensure `install.sh` still renders them correctly and that the
placeholders stay in sync.
