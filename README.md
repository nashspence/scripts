# when

when is a containerised utility for inferring the creation timestamp of media files. The script wraps metadata probes (EXIF, FFmpeg, MediaInfo, and common sidecars), applies a scoring heuristic, and prints the most trustworthy result.

## Repository layout

- `Containerfile` – build definition for the runtime image.
- `when.py` – main entrypoint for the tool.
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
podman build -t when .
podman run --rm -v "$PWD:/workspace" when --help
```

## Release

Cut a semantic version tag to publish a new container image to GitHub Container Registry:

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The release workflow builds multi-architecture images and pushes them to `ghcr.io/nashspence/when` with the tag name, `latest`, and the Git commit SHA.
