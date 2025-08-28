# AGENTS

This file applies to the entire repository.

## Development workflow
1. Format & lint all changes:
   ```
   pre-commit run --files <files>
   ```
2. Run dependency-free unit tests:
   ```
   pytest
   ```
3. Do **not** run integration tests locally. GitHub Actions executes:
   ```
   pytest -m integration
   ```
4. GitHub Actions CI runs `pre-commit run --all-files`, `pytest`, and `pytest -m integration` on all supported platforms.

Scripts are containerised for cross‑platform use with Podman. Host-specific helpers (e.g. in `osx/`) are only for tasks that do not containerise cleanly.

Each script directory maintains a gauge-style `spec.md` with test scenarios. Use a single spec per platform-specific directory (e.g. `osx/spec.md`). If needed, keep script-specific terminology in a `glossary.md` alongside the spec.


## Unit tests
- Place tests in a `tests/` directory adjacent to the code.
- Mock external commands and filesystem interactions; unit tests should exercise only the code under test.
