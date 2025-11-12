# fitdisk

fitdisk is a containerised utility for grouping media files into numbered directories that fit within a target size. The script is designed to run inside a Podman container and uses Python's standard library to measure files, plan bundles, and optionally move them into output folders.

## Repository layout

- `Containerfile` – build definition for the runtime image.
- `fitdisk.py` – main entrypoint for the tool.
- `spec.md` – Gauge specification describing expected behaviour.
- `tests/` – unit tests for the script.

## Development

Set up a virtual environment and install the tooling you need for development:

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

Build and run the container image locally to exercise the full workflow:

```bash
podman build -t fitdisk .
podman run --rm -v "$PWD:/workspace" fitdisk --help
```

## Release

Cut a semantic version tag to publish a new container image to GitHub Container Registry:

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The release workflow builds multi-architecture images and pushes them to `ghcr.io/nashspence/fitdisk` with the tag name, `latest`, and the Git commit SHA.
