#!/bin/zsh
set -euo pipefail
# Auto-generated wrapper. Invokes 'run-podman-script' against a release.yaml only.
export DR_WRAPPER_NAME="%NAME%"
exec run-podman-script -r "%ABS%" "$@"
