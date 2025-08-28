# Scripts

Utility scripts for cross-platform workflows.

## Development

Install and run the pre-commit hooks for changed files:

```bash
pre-commit install --install-hooks
pre-commit run --files <files>
```

Hooks cover formatting, linting, strict type checks with `mypy`, and Gauge spec validation.
The Gauge CLI is installed automatically via pre-commit.

Run tests:

```bash
pytest
```
