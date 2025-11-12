#!/bin/sh
# install.sh — install or remove the use-machine launch agent.

set -eu
[ "${DEBUG:-}" ] && set -x

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
install_root_default="$HOME/Library/Application Support/use-machine"
install_root=${INSTALL_ROOT:-$install_root_default}
launch_agents_dir="$HOME/Library/LaunchAgents"
agent_label="com.nashspence.use-machine.podman-machine"
plist_target="$launch_agents_dir/${agent_label}.plist"
uid_num=$(id -u)
machine=${USE_MACHINE_NAME:-com.nashspence.use-machine}

escape_sed() {
    printf '%s' "$1" | sed 's/[\\/&]/\\&/g'
}

install_files() {
    bin_dir="$install_root/bin"
    agent_dir="$install_root/launch-agent"
    template="$script_dir/osx/launch-agent/com.nashspence.use-machine.podman-machine.plist"

    mkdir -p "$bin_dir" "$agent_dir" "$launch_agents_dir"

    cp "$script_dir/bin/use-machine" "$bin_dir/use-machine"
    chmod 0755 "$bin_dir/use-machine"

    cp "$script_dir/osx/launch-agent/use-machine-agent" "$agent_dir/use-machine-agent"
    chmod 0755 "$agent_dir/use-machine-agent"

    root_escaped=$(escape_sed "$install_root")
    machine_escaped=$(escape_sed "$machine")

    sed \
        -e "s/%INSTALL_ROOT%/${root_escaped}/g" \
        -e "s/%MACHINE%/${machine_escaped}/g" \
        -e "s/%UID_NUM%/${uid_num}/g" \
        "$template" >"$plist_target"
    chmod 0644 "$plist_target"

    launchctl bootout "gui/${uid_num}/$agent_label" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/${uid_num}" "$plist_target"
    launchctl kickstart -k "gui/${uid_num}/$agent_label" >/dev/null 2>&1 || true

    user_bin="$HOME/bin"
    mkdir -p "$user_bin"
    ln -snf "$bin_dir/use-machine" "$user_bin/use-machine"

    printf 'Installed use-machine to %s\n' "$install_root"
    printf 'LaunchAgent loaded as %s\n' "$agent_label"
    printf 'A symlink was created at %s\n' "$user_bin/use-machine"
}

uninstall_files() {
    launchctl bootout "gui/${uid_num}/$agent_label" >/dev/null 2>&1 || true
    rm -f "$plist_target"
    rm -f "$HOME/bin/use-machine" 2>/dev/null || true
    rm -rf "$install_root"
    printf 'Removed use-machine installation from %s\n' "$install_root"
}

case "${1:-}" in
    --uninstall)
        uninstall_files
        ;;
    "")
        install_files
        ;;
    *)
        cat <<USAGE >&2
Usage:
  $0            Install use-machine for the current user
  $0 --uninstall Remove the installed launch agent and files
USAGE
        exit 2
        ;;
esac
