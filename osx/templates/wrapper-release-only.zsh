#!/bin/zsh
set -euo pipefail
# Auto-generated wrapper. Invokes 'podman-script-machine run' against a release.yaml only.
export DR_WRAPPER_NAME="%NAME%"
exec podman-script-machine run -r "%ABS%" "$@"
