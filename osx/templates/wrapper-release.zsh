#!/bin/zsh
set -euo pipefail
# Auto-generated wrapper. Invokes 'podman-scripts-machine run' against a specific build file.
export DR_WRAPPER_NAME="%NAME%"
exec podman-scripts-machine run -f "%ABS%" -r "%REL%" "$@"
