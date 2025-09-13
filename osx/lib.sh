#!/bin/sh

# Adjust PATH using the repository directory provided in PODMAN_SCRIPTS_DIR.
if [ -z "${PODMAN_SCRIPTS_DIR:-}" ]; then
  return 0 2>/dev/null || exit 0
fi

PATH="${PODMAN_SCRIPTS_DIR}/bin:${PODMAN_SCRIPTS_DIR}/osx/bin:${PATH}"
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

pause() {
    msg=${1:-}; delay=${2:-5}
    if [ -t 0 ]; then
        [ -n "$msg" ] && printf '%s' "$msg" >&2
        IFS= read -r _ || return 130
    else
        sleep "$delay"
    fi
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
    delay=5; max=; prompt=; hook=
    while [ $# -gt 0 ]; do
        case $1 in
            -d) delay=$2; shift 2 ;;
            -n) max=$2; shift 2 ;;
            -p) prompt=$2; shift 2 ;;
            --hook|-H) hook=$2; shift 2 ;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    [ $# -gt 0 ] || { warn "usage: retry [-d secs] [-n max] [-p prompt] [--hook handler] -- cmd ..."; return 2; }

    tries=0
    while :; do
        "$@"; rc=$?
        [ "$rc" -eq 0 ] && return 0
        tries=$((tries + 1))
        [ -n "$hook" ] && "$hook" "$rc" "$@"
        [ -n "$max" ] && [ "$tries" -ge "$max" ] && return "$rc"
        if [ -t 0 ]; then
            if [ -n "$prompt" ]; then
                printf '%s' "$prompt" >&2
            else
                printf 'Command failed (rc=%s). Press Enter to retry (Ctrl-C to abort)...' "$rc" >&2
            fi
            IFS= read -r _ || return 130
        else
            sleep "$delay"
        fi
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
