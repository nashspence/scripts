# qcut

qcut is a containerised utility for assembling highlight reels from directories of source videos. The script mirrors the original shell workflow: probe durations, plan clip lengths, encode each segment with SVT-AV1, and append them into a final Matroska file with timestamp overlays.

## Repository layout

- `Containerfile` – build definition for the runtime image.
- `qcut.py` – main entrypoint for the tool.
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
podman build -t qcut .
podman run --rm \
  -v "$PWD/in:/in:ro" \
  -v "$PWD/out:/out" \
  qcut --src-dir /in --autoedit-dir /out --svt-lp 6
```

## Release

Cut a semantic version tag to publish a new container image to GitHub Container Registry:

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The release workflow builds multi-architecture images and pushes them to `ghcr.io/nashspence/qcut` with the tag name, `latest`, and the Git commit SHA.
