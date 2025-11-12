# AGENTS

This file applies to the entire repository.

The repository packages a single containerised script, `qcut.py`. Keep the project aligned with this layout when adding or updating files.

## Development workflow
1. Format & lint all changes:
   ```
   pre-commit run --all-files
   ```
2. Run dependency-free unit tests:
   ```
   pytest
   ```
3. Update `spec.md` whenever `qcut.py` or its CLI surface changes.

Avoid adding linter or formatter ignore comments (for example, `# noqa`, `# fmt: off`) unless absolutely necessary. When such comments are required, include an inline explanation of their necessity, justify why they are acceptable, and note this explicitly in the commit message.

## Documentation and tests
- Keep `spec.md` following modern Gauge conventions with `Scenario:` headings and `Given`/`When`/`Then` steps that map directly to the CLI actions.
- Place tests in the `tests/` directory adjacent to `qcut.py` and mock external commands or filesystem interactions so unit tests exercise only the code under test.
