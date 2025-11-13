# posix-pipeline

posix-pipeline is a lightweight collection of POSIX-compliant shell helpers that make it easier to compose predictable pipelines.
Source `posix-pipeline.sh` from your own scripts to add consistent logging, retry, and marker primitives.

## Installation

### Linux and other POSIX shells

```sh
./install.sh
```

Pass `--uninstall` to remove the configuration block that the installer adds to your shell profiles.

### macOS (zsh)

```sh
./osx/install.sh
```

The macOS helper adds a reusable block to `~/.profile`, `~/.zprofile`, and `~/.zshrc` so shells on the host and in login
sessions can source the helpers. Remove the configuration block with `./osx/install.sh --uninstall`.

### Manual sourcing

If you prefer not to modify your shell configuration, source the script directly:

```sh
. "/path/to/posix-pipeline/posix-pipeline.sh"
```

## Repository layout

- `posix-pipeline.sh` – main entrypoint providing the helper functions.
- `spec.md` – Gauge specification describing the expected behaviour.
- `tests/` – shell-based tests covering the helpers.
- `install.sh` – installation helper for Linux and other POSIX environments.
- `osx/install.sh` – installation helper for macOS workstations.

## Development

Install the development tools (for example via `pipx install pre-commit`), then run the checks locally before committing:

```sh
pre-commit run --all-files
./tests/test_posix_pipeline.sh
```

Update `spec.md` whenever `posix-pipeline.sh` or its documented behaviour changes.
