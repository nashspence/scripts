# AGENTS

This file applies to the entire repository.

The repository packages a single containerised script, `padimg.py`. Keep the
layout aligned with [`nashspence/vcrunch`](https://github.com/nashspence/vcrunch):
`padimg.py`, `Containerfile`, `spec.md`, `tests/`, and supporting config files at
repo root.

## Development workflow
1. Format & lint all changes:
   ```
   pre-commit run --all-files
   ```
2. Run dependency-free unit tests:
   ```
   pytest
   ```
3. Update `spec.md` whenever `padimg.py` or its CLI surface changes.

Avoid adding linter or formatter ignore comments unless absolutely necessary. If
an ignore is required, document the reason inline and mention it in the commit
message.

## Documentation and tests
- Keep `spec.md` following modern Gauge conventions with `Scenario:` headings and
  `Given`/`When`/`Then` steps that map directly to the CLI actions.
- Place tests in the `tests/` directory adjacent to `padimg.py` and mock external
  commands or filesystem interactions so unit tests exercise only the code under test.
