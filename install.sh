#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
Usage: ./install.sh [--uninstall]

Installs or removes the on-mount launch agent for the current user.
Set the following environment variables to override defaults:
  AGENT_ROOT          Base directory for installed assets (default: "$HOME/Library/Application Support/on-mount-agent")
  LAUNCH_AGENTS_DIR   Destination for launch agent plists (default: "$HOME/Library/LaunchAgents")
  LOG_DIR             Directory for log files (default: "$HOME/Library/Logs/on-mount-agent")
  TRIGGERS_DIR        Directory scanned for trigger executables (default: "$AGENT_ROOT/triggers")
EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

uninstall=false
if [ "${1:-}" = "--uninstall" ]; then
    uninstall=true
    shift
fi

if [ $# -gt 0 ]; then
    printf 'Unknown option: %s\n' "$1" >&2
    usage >&2
    exit 1
fi

if [ "$(uname -s)" != "Darwin" ]; then
    printf 'This installer only supports macOS.\n' >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf 'python3 is required for templating launch agent plists.\n' >&2
    exit 1
fi

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
template_root="${script_dir}/launch-agents"

agent_root=${AGENT_ROOT:-"$HOME/Library/Application Support/on-mount-agent"}
launch_agents_dir=${LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
log_dir=${LOG_DIR:-"$HOME/Library/Logs/on-mount-agent"}
triggers_dir=${TRIGGERS_DIR:-"$agent_root/triggers"}
bin_dir="${agent_root}/bin"
uid_num=$(id -u)

ensure_dirs() {
    mkdir -p "$agent_root" "$bin_dir" "$log_dir" "$triggers_dir" "$launch_agents_dir"
}

swift_compile() {
    if command -v swiftc >/dev/null 2>&1; then
        swiftc "$@"
    elif command -v xcrun >/dev/null 2>&1 && xcrun -f swiftc >/dev/null 2>&1; then
        xcrun swiftc "$@"
    else
        printf 'swiftc not found. Install Xcode Command Line Tools and re-run.\n' >&2
        exit 1
    fi
}

render_plist() {
    src=$1
    dest=$2
    python3 - "$src" "$dest" "$agent_root" "$log_dir" "$triggers_dir" "$uid_num" <<'PY'
import pathlib
import sys

src, dest = map(pathlib.Path, sys.argv[1:3])
agent_root, log_dir, triggers_dir, uid = sys.argv[3:7]
text = src.read_text()
for key, value in (
    ("__AGENT_ROOT__", agent_root),
    ("__LOG_DIR__", log_dir),
    ("__TRIGGERS_DIR__", triggers_dir),
    ("__UID__", uid),
):
    text = text.replace(key, value)
dest.write_text(text)
PY
    chmod 0644 "$dest"
}

load_launch_agent() {
    label=$1
    plist=$2
    launchctl bootout "gui/${uid_num}" "$plist" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/${uid_num}" "$plist"
    launchctl kickstart -k "gui/${uid_num}/${label}" >/dev/null 2>&1 || true
}

remove_launch_agent() {
    label=$1
    plist=$2
    launchctl bootout "gui/${uid_num}" "$plist" >/dev/null 2>&1 || true
    rm -f "$plist"
}

install_agents() {
    ensure_dirs

    printf '→ Installing into %s\n' "$agent_root"

    swift_src="${template_root}/on-mount/on-mount.swift"
    swift_out="${bin_dir}/on-mount"
    printf '  • Compiling on-mount listener\n'
    swift_compile -O -framework AppKit -o "$swift_out" "$swift_src"
    chmod 0755 "$swift_out"

    printf '  • Writing launch agents\n'
    onmount_plist="${launch_agents_dir}/com.nashspence.scripts.on-mount.plist"
    render_plist "${template_root}/on-mount/com.nashspence.scripts.on-mount.plist" "$onmount_plist"

    printf '  • Loading launch agents\n'
    load_launch_agent "com.nashspence.scripts.on-mount" "$onmount_plist"

    printf '\nInstallation complete!\n'
    printf '  Trigger scripts live in: %s\n' "$triggers_dir"
    printf '  Logs are written to:    %s\n' "$log_dir"
}

uninstall_agents() {
    printf '→ Uninstalling on-mount agent\n'
    onmount_plist="${launch_agents_dir}/com.nashspence.scripts.on-mount.plist"

    remove_launch_agent "com.nashspence.scripts.on-mount" "$onmount_plist"

    rm -rf "$agent_root"
    printf 'Removed %s\n' "$agent_root"
    printf 'You may remove %s manually if desired.\n' "$log_dir"
}

if $uninstall; then
    uninstall_agents
else
    install_agents
fi
