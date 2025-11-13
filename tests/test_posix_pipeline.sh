#!/bin/sh
set -eu

repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
orig_dir=$(pwd -P)
cd "$repo_dir"
# shellcheck source=./posix-pipeline.sh
. ./posix-pipeline.sh
cd "$orig_dir"

failures=0
total=0

run_test() {
    name=$1
    shift
    total=$((total + 1))
    printf '%s... ' "$name"
    set +e
    "$@"
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
        printf 'ok\n'
    else
        printf 'fail (exit %s)\n' "$rc"
        failures=$((failures + 1))
    fi
}

mode_of() {
    path=$1
    if stat -c %a "$path" 2>/dev/null; then
        :
    else
        stat -f %Lp "$path"
    fi
}

test_mark_done_creates_marker() {
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT INT TERM HUP
    mark "done" "$tmp/job.marker"
    [ -f "$tmp/job.marker" ] || return 1
    [ "$(mode_of "$tmp/job.marker")" = "600" ] || return 1
    rm -rf "$tmp"
    trap - EXIT INT TERM HUP
}

test_mark_check_detects_existing_marker() {
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT INT TERM HUP
    : >"$tmp/job.marker"
    set +e
    mark "check" "$tmp/job.marker"
    rc=$?
    set -e
    rm -rf "$tmp"
    trap - EXIT INT TERM HUP
    [ "$rc" -eq 1 ]
}

test_retry_returns_failure_without_prompt_when_non_tty() {
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT INT TERM HUP
    err="$tmp/stderr"
    set +e
    retry sh -c 'exit 42' </dev/null 2>"$err"
    rc=$?
    set -e
    [ "$rc" -eq 42 ] || return 1
    [ ! -s "$err" ] || return 1
    rm -rf "$tmp"
    trap - EXIT INT TERM HUP
}

run_test "mark done creates marker" test_mark_done_creates_marker
run_test "mark check detects existing marker" test_mark_check_detects_existing_marker
run_test "retry propagates failure without prompting when non-tty" test_retry_returns_failure_without_prompt_when_non_tty

printf '\n%d tests, %d failures\n' "$total" "$failures"
if [ "$failures" -ne 0 ]; then
    exit 1
fi
