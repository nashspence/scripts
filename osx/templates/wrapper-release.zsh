#!/bin/zsh
set -euo pipefail
# Auto-generated wrapper. Invokes 'podman-script-machine run' against a specific build file.
export DR_WRAPPER_NAME="%NAME%"
exec podman-script-machine run -f "%ABS%" -r "%REL%" "$@"
