#!/bin/zsh
set -euo pipefail
# Auto-generated wrapper. Invokes 'run-podman-script' against a specific build file.
export DR_WRAPPER_NAME="%NAME%"
exec run-podman-script -f "%ABS%" "$@"
