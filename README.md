# mkiso

mkiso is a containerised utility for packaging a directory tree into a boot-agnostic ISO image using `genisoimage`. The script is designed to run inside a Podman container so the host only needs a container runtime.

## Repository layout

- `Containerfile` – build definition for the runtime image.
- `mkiso.py` – main entrypoint for the tool.
- `spec.md` – Gauge specification describing expected behaviour.
- `tests/` – unit tests for the script.

## Development

Set up a virtual environment and install the tooling required for development:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install pre-commit pytest
```

Run the automated checks before submitting changes:

```bash
pre-commit run --all-files
pytest
```

Build and run the container image locally to exercise the workflow end-to-end:

```bash
podman build -t mkiso .
podman run --rm -v "$PWD:/workspace" mkiso --help
```

## Release

Cut a semantic version tag to publish a new container image to GitHub Container Registry:

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The release workflow builds multi-architecture images and pushes them to `ghcr.io/nashspence/mkiso` with the tag name, `latest`, and the Git commit SHA.
