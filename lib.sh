#!/bin/sh

# Adjust PATH using the repository directory provided in PODMAN_SCRIPTS_DIR.
if [ -z "${PODMAN_SCRIPTS_DIR:-}" ]; then
    return 0 2>/dev/null || exit 0
fi

PATH="${PODMAN_SCRIPTS_DIR}/bin:${PATH}"
export PATH

warn() { printf '%s\n' "$*" >&2; }
die()  { warn "$@"; exit 1; }

abort() {
    code=${1:-1}
    trap '' INT TERM HUP QUIT
    kill -TERM 0 2>/dev/null || :
    wait 2>/dev/null || :
    exit "$code"
}

onfail() {
    handler=$1; shift
    [ "x$1" = "x--" ] || { warn "usage: onfail handler -- cmd ..."; return 2; }
    shift
    "$@"; rc=$?
    [ "$rc" -eq 0 ] || "$handler" "$rc" "$@"
    return "$rc"
}

retry() {
    while :; do
        "$@" && return 0
        s=$?
        [ -t 0 ] || return "$s"
        printf 'Failed (exit %d). Retry? [y/N] ' "$s" >&2
        IFS= read -r yn || return "$s"
        case $yn in [Yy]*) ;; *) return "$s";; esac
    done
}

mark() {
    sub=$1
    case $sub in
        check)
            [ -n "$2" ] || return 2
            [ -f "$2" ] && return 1 || return 0
            ;;
        done)
            [ -n "$2" ] || return 2
            m=$2
            case $m in */*) d=${m%/*}; [ -d "$d" ] || mkdir -p "$d";; esac
            ( umask 077; : > "$m" ) || :
            ;;
        *) return 2 ;;
    esac
}
