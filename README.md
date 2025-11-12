# use-machine

use-machine keeps a Podman machine awake while a process runs. It pairs a small
`use-machine` CLI with a macOS LaunchAgent that lazily starts the VM when a
client connects and stops it once the last client disconnects.

The repository is intentionally small and mirrors the conventions used in
[`nashspence/vcrunch`](https://github.com/nashspence/vcrunch): a single
POSIX-friendly entrypoint, a matching specification, and an automated release
pipeline triggered by semantic tags.

## Repository layout

- `bin/use-machine` – CLI that holds the socket connection open for a PID.
- `install.sh` – macOS installer that provisions the LaunchAgent and CLI.
- `osx/launch-agent/` – socket-activated Podman machine agent and plist.
- `spec.md` – Gauge-style specification describing behaviour.
- `.github/workflows/release-on-tag.yml` – builds distributable archives on
  tagged releases.

## Requirements

- macOS 13 or newer.
- [Podman](https://podman.io/) with a configured machine matching the label in
  the LaunchAgent (defaults to `com.nashspence.use-machine`).
- `nc` (BSD netcat, shipped with macOS).

## Installation

Download a release archive and run:

```sh
./install.sh
```

The script installs to `~/Library/Application Support/use-machine`, writes the
LaunchAgent into `~/Library/LaunchAgents/com.nashspence.use-machine.podman-machine.plist`,
loads it via `launchctl`, and creates a `~/bin/use-machine` symlink for
convenient CLI access.

Uninstall with:

```sh
./install.sh --uninstall
```

## Usage

Wrap long-lived commands so the machine remains running until they complete:

```sh
machine=$(use-machine $$)
podman --connection "$machine" run …
```

The CLI prints the machine name immediately after the LaunchAgent reports that
Podman is ready, then holds the socket connection open until the watched PID
exits. Once all holders release the socket, the agent stops the Podman machine.

## Development

- Scripts are POSIX-compliant `sh`.
- Keep the specification in `spec.md` in sync with behaviour changes.
- Run shellcheck locally before committing (if available).

## Releasing

Push a tag matching `x.y.z` to trigger the release workflow. The workflow
creates a `use-machine-x.y.z-macos.tar.gz` archive containing the CLI,
installer, and LaunchAgent assets and attaches it to the GitHub release.
