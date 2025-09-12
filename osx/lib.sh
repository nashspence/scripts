#!/usr/bin/env zsh

# Adjust PATH using the repository directory provided in PODMAN_SCRIPTS_DIR.

# Skip if the variable is unset.
[[ -n "${PODMAN_SCRIPTS_DIR:-}" ]] || return 0

export PATH="${PODMAN_SCRIPTS_DIR}/.wrappers:${PODMAN_SCRIPTS_DIR}/osx/bin:$PATH"
