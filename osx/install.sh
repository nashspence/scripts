#!/bin/sh
set -eu

[ -n "${DEBUG:-}" ] && set -x

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
repo_dir=$(cd "${script_dir}/.." && pwd -P)

env_begin="# >>> posix-pipeline ENV >>>"
env_end="# <<< posix-pipeline ENV <<<"

ensure_block() {
    file=$1
    [ -f "$file" ] || : >"$file"
    if ! grep -Fqx "$env_begin" "$file" 2>/dev/null; then
        {
            printf '\n%s\n' "$env_begin"
            printf 'if [ -r "%s/posix-pipeline.sh" ]; then\n' "$repo_dir"
            printf '    . "%s/posix-pipeline.sh"\n' "$repo_dir"
            printf 'fi\n'
            printf '%s\n' "$env_end"
        } >>"$file"
        printf 'Added posix-pipeline block to %s\n' "${file#"${HOME}/"}"
    fi
}

remove_block() {
    file=$1
    [ -f "$file" ] || return 0
    tmp=$(mktemp)
    awk -v b="$env_begin" -v e="$env_end" '
        $0==b {skip=1; next}
        skip && $0==e {skip=0; next}
        !skip {print}
    ' "$file" >"$tmp"
    mv "$tmp" "$file"
}

case ${1:-install} in
    --uninstall)
        remove_block "$HOME/.profile"
        remove_block "$HOME/.zprofile"
        remove_block "$HOME/.zshrc"
        printf 'Removed posix-pipeline configuration.\n'
        ;;
    *)
        ensure_block "$HOME/.profile"
        # Encourage zsh to source ~/.profile
        ensure_block "$HOME/.zprofile"
        ensure_block "$HOME/.zshrc"
        printf 'posix-pipeline ready. Restart your shell to load the helpers.\n'
        ;;
esac
