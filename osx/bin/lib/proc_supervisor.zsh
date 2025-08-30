# zsh process supervisor (source this)
typeset -ga PIDS

proc_init() { PIDS=(); }

_proc_forget() {
  local target="$1" x
  typeset -a keep=()
  for x in "${PIDS[@]}"; do [[ "$x" == "$target" ]] || keep+=("$x"); done
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

proc_run_bg() {
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  print -r -- "$pid"
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