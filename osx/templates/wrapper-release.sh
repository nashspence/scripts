#!/bin/sh
set -eu
# Auto-generated wrapper. Runs a portable container image.
export DR_WRAPPER_NAME="%NAME%"
use-scripts-machine "$$" &
img=$(nsimg "%NAME%")
exec podman run --rm "$img" "$@"
