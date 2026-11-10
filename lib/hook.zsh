# dojo shell hook（zsh）
# 由 ~/.zshrc 里 # >>> dojo >>> 标记块 source 进来

[[ -o interactive ]] || return 0

DOJO_STATE_DIR="${DOJO_STATE_DIR:-$HOME/.local/state/dojo}"
DOJO_CTX="$DOJO_STATE_DIR/ctx.tsv"
DOJO_ERR="$DOJO_STATE_DIR/stderr.log"
mkdir -p "$DOJO_STATE_DIR" 2>/dev/null

__dojo_last=""

__dojo_hook() {
  local code=$? cmd off

  cmd=$(fc -ln -1 2>/dev/null | sed 's/^[[:space:]]*//')
  [ -z "$cmd" ] && return $code
  [ "$cmd" = "$__dojo_last" ] && return $code
  __dojo_last=$cmd

  cmd=${cmd//$'\n'/ }
  cmd=${cmd//$'\x1f'/ }

  off=""
  [ -f "$DOJO_ERR" ] && off=$(stat -c %s "$DOJO_ERR" 2>/dev/null)

  printf '%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
    "${EPOCHSECONDS:-$(date +%s)}" "$code" "$PWD" "$cmd" "${off:-}" >> "$DOJO_CTX"

  if [ "$(stat -c %s "$DOJO_CTX" 2>/dev/null || echo 0)" -gt 262144 ]; then
    tail -n 500 "$DOJO_CTX" > "$DOJO_CTX.tmp" 2>/dev/null && mv "$DOJO_CTX.tmp" "$DOJO_CTX"
  fi

  return $code
}

if [ -f "$HOME/.config/dojo/config.toml" ] \
   && grep -A8 '^\[context\]' "$HOME/.config/dojo/config.toml" 2>/dev/null | grep -q 'capture_stderr *= *true'; then
  : >> "$DOJO_ERR"
  exec 2> >(tee -a "$DOJO_ERR" >&2)
fi

autoload -Uz add-zsh-hook 2>/dev/null
if command -v add-zsh-hook >/dev/null 2>&1; then
  add-zsh-hook precmd __dojo_hook
else
  precmd_functions+=(__dojo_hook)
fi
