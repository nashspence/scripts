#!/usr/bin/env bash
set -euo pipefail

VERSION="1.6.20"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/gauge"
BIN="$CACHE_DIR/gauge"

if [ ! -x "$BIN" ]; then
  TMP_DIR=$(mktemp -d)
  ZIP_URL="https://github.com/getgauge/gauge/releases/download/v${VERSION}/gauge-${VERSION}-linux.x86_64.zip"
  curl -fsSL "$ZIP_URL" -o "$TMP_DIR/gauge.zip"
  mkdir -p "$CACHE_DIR"
  unzip -q "$TMP_DIR/gauge.zip" -d "$CACHE_DIR"
  chmod +x "$BIN"
  rm -rf "$TMP_DIR"
fi

exec "$BIN" format "$@"
