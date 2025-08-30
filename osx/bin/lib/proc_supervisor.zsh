# zsh process supervisor (source this)
emulate -L zsh
setopt err_return pipefail

typeset -ga PIDS=()

proc_init() { PIDS=(); }

_proc_forget() {
  local t="$1" x; typeset -a keep=()
  for x in "${PIDS[@]}"; do [[ "$x" == "$t" ]] || keep+=("$x"); done
  PIDS=("${keep[@]}")
}

proc_kill() {
  local p
  for p in "$@"; do
    kill -INT -- "$p" 2>/dev/null || kill -TERM -- "$p" 2>/dev/null || true
  done
}

proc_cleanup() {
  local p
  proc_kill "${PIDS[@]}"
  for p in "${PIDS[@]}"; do wait "$p" 2>/dev/null || true; done
}

proc_traps() {
  trap 'proc_cleanup; exit 130' INT
  trap 'proc_cleanup; exit 143' TERM
  trap 'proc_cleanup; exit 129' HUP
  trap 'proc_cleanup' EXIT
}

proc_run() {
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  wait "$pid"
  local rc=$?
  _proc_forget "$pid"
  return $rc
}

# usage: proc_run_bg <outvar> <cmd> [args...]
proc_run_bg() {
  local __outvar="$1"; shift
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  eval "$__outvar=$pid"
}

proc_wait() {
  local pid="$1"
  wait "$pid"
  local rc=$?
  _proc_forget "$pid"
  return $rc
}

proc_kill_and_wait() {
  local pid="$1"
  proc_kill "$pid"
  wait "$pid" 2>/dev/null || true
  _proc_forget "$pid"
}