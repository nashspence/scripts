# padimg

padimg is a containerised utility for padding images to a target aspect ratio by adding
neutral gray bars. The script is designed to run inside a Podman container and uses
Pillow to read, transpose, and save images without resampling the original pixels.

## Repository layout

- `Containerfile` – build definition for the runtime image.
- `padimg.py` – main entrypoint for the tool.
- `spec.md` – Gauge specification describing expected behaviour.
- `tests/` – unit tests for the script.

## Usage

Run the published image against files in the current directory:

```bash
podman run --rm -v "$PWD:/work" -w /work ghcr.io/nashspence/padimg:latest input.jpg --ratio 4:5 --gray 32
```

The container entrypoint is the script itself, so arguments map directly to the CLI.

## Development

Set up a virtual environment and install the tooling you need for development:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements-dev.txt
pip install pre-commit
```

Run the automated checks before submitting changes:

```bash
pre-commit run --all-files
pytest
```

Build and run the container image locally to exercise the full workflow:

```bash
podman build -t padimg .
podman run --rm -v "$PWD:/workspace" -w /workspace padimg --help
```

## Release

Cut a semantic version tag to publish a new container image to GitHub Container Registry:

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The release workflow builds multi-architecture images and pushes them to `ghcr.io/nashspence/padimg`
with the tag name, `latest`, and the Git commit SHA.
