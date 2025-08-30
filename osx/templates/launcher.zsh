#!/bin/zsh
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "$APP_DIR/Resources/podman-scripts-machine-agent"
