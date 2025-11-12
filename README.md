# on-mount-agent

on-mount-agent packages a single macOS launch agent that watches for mounted volumes containing a
`.com.nashspence.scripts.on-mount.id` marker file and opens Terminal to run the named trigger script.

## Repository layout

- `install.sh` – Installer/uninstaller for the launch agent.
- `launch-agents/on-mount/` – Swift source and launchd template for the on-mount listener.

## Installation

Download the latest `on-mount-agent-macos-*.zip` release and run:

```bash
unzip on-mount-agent-macos-*.zip
cd on-mount-agent
./install.sh
```

By default the installer places assets under `~/Library/Application Support/on-mount-agent` and writes
launch agent plists to `~/Library/LaunchAgents`. Environment variables allow overrides; run
`./install.sh --help` to see the available options. Re-run the script with `--uninstall` to remove the
agent.

### Trigger scripts

When a volume is mounted the on-mount agent looks for a marker file named
`.com.nashspence.scripts.on-mount.id` at the root of the volume. The first line of the marker file
should contain the name of an executable located in the triggers directory (default:
`~/Library/Application Support/on-mount-agent/triggers`). The agent opens Terminal and executes the
matching script, passing the mounted volume path as the first argument.

## Development

This repository follows the conventions used in [nashspence/vcrunch](https://github.com/nashspence/vcrunch).
Before submitting changes, format Swift sources with `swift-format` if available and keep shell scripts
POSIX-compliant. The installer expects to run on macOS and requires `python3` and the Swift compiler to
be present.

## Release

Tag the repository with a semantic version (`x.y.z`) to trigger the release workflow:

```bash
git tag -a 1.2.3 -m "1.2.3"
git push origin 1.2.3
```

The GitHub Actions workflow builds a signed ZIP archive containing the installer and launch agent
assets and attaches it to the corresponding GitHub release.
