# qcut

`qcut` automatically assembles highlight reels from a directory of source videos. It mirrors the behaviour of the original shell workflow: probe durations, plan clip lengths, encode each segment with SVT-AV1, and append them into a final Matroska file with timestamp overlays.

## Usage

Build the container image and run it against a directory of source clips:

```bash
podman build -t qcut .
podman run --rm \
  -v "$PWD/in:/in:ro" \
  -v "$PWD/out:/out" \
  qcut --src-dir /in --autoedit-dir /out --svt-lp 6
```

Adjust the `--target`, `--min`, `--max`, and `--svt-*` options to suit your edit plan. The container will persist its resumable manifest inside the output directory.

## Development

Install and run the pre-commit hooks for changed files:

```bash
pre-commit install --install-hooks
pre-commit run --files <files>
```

Run unit tests:

```bash
pytest
```
