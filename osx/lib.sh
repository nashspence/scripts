#!/bin/sh

# Adjust PATH using the repository directory provided in PODMAN_SCRIPTS_DIR.
if [ -z "${PODMAN_SCRIPTS_DIR:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
PATH="${PODMAN_SCRIPTS_DIR}/.wrappers:${PODMAN_SCRIPTS_DIR}/osx/bin:${PATH}"
export PATH
