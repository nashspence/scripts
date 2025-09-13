#!/bin/sh
set -eu
# Auto-generated wrapper. Invokes 'podman-scripts-machine run' against a release.yaml only.
export DR_WRAPPER_NAME="%NAME%"
exec podman-scripts-machine run -r "%ABS%" "$@"
