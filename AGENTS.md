# AGENTS

This file applies to the entire repository.

## Development workflow
1. Format & lint all changes:
   ```
   pre-commit run --all-files
   ```
2. Run dependency-free unit tests:
   ```
   pytest
   ```
3. For portable services with a `Containerfile`, update `spec.md`.

Avoid adding linter or formatter ignore comments (for example, `# noqa`, `# fmt: off`) unless absolutely necessary. When such comments are required, include an inline explanation of their necessity, justify why they are acceptable, and note this explicitly in the commit message.

Scripts are containerised for cross‑platform use with Podman.

When writing shell scripts, prefer POSIX-compliant `sh` and use other shells only when absolutely necessary.
Each Podman script directory must include a `spec.md` written using modern Gauge conventions (`Scenario:` headings and `Given`/`When`/`Then` steps with parameter placeholders). Break steps into single, atomic actions and expectations to keep scenarios easily testable. For CLI specs, pass each flag or argument in its own step before the final run step. Specs should contain the minimal scenarios necessary for complete coverage of the script's features, including every command-line flag and argument. Use a single spec per platform-specific directory (e.g. `osx/spec.md`). If needed, keep script-specific terminology in a `glossary.md` alongside the spec.

## Unit tests
- Place tests in a `tests/` directory adjacent to the code.
- Mock external commands and filesystem interactions; unit tests should exercise only the code under test.
