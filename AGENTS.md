# AGENTS

This file applies to the entire repository.

The repository provides a single POSIX shell helper, `posix-pipeline.sh`. Keep the project focused on sourcing that script from
local installs rather than container images.

## Development workflow
1. Format & lint all shell changes:
   ```
   pre-commit run --all-files
   ```
2. Run the shell tests:
   ```
   ./tests/test_posix_pipeline.sh
   ```
3. Update `spec.md` whenever `posix-pipeline.sh` or its documented behaviour changes.

Avoid adding linter or formatter ignore comments (for example, `# shellcheck disable=SCXXXX`) unless absolutely necessary. When
such comments are required, include an inline explanation of their necessity, justify why they are acceptable, and note this
explicitly in the commit message.

## Documentation and tests
- Keep `spec.md` following modern Gauge conventions with `Scenario:` headings and `Given`/`When`/`Then` steps that map directly
to the script actions.
- Place tests in the `tests/` directory adjacent to `posix-pipeline.sh` and use POSIX shell to exercise the helpers without
assuming Python tooling.
