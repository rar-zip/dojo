# dojo shell hook（bash）
# 由 ~/.bashrc 里 # >>> dojo >>> 标记块 source 进来

case $- in
  *i*) ;;
  *) return 0 ;;
esac

DOJO_STATE_DIR="${DOJO_STATE_DIR:-$HOME/.local/state/dojo}"
DOJO_CTX="$DOJO_STATE_DIR/ctx.tsv"
DOJO_ERR="$DOJO_STATE_DIR/stderr.log"
mkdir -p "$DOJO_STATE_DIR" 2>/dev/null

__dojo_armed=0
__dojo_ran=0

# 用 DEBUG trap 判断「这一轮到底有没有真的执行命令」
# 只看 history 编号不行：HISTCONTROL=ignoreboth 时连续两条一样的命令编号不变
__dojo_preexec() {
  [ "$__dojo_armed" = 1 ] || return 0
  case "$BASH_COMMAND" in
    __dojo_hook*|__dojo_preexec*) return 0 ;;
  esac
  __dojo_armed=0
  __dojo_ran=1
}
trap '__dojo_preexec' DEBUG

__dojo_hook() {
  local code=$? h num cmd off
  if [ "$__dojo_ran" != 1 ]; then
    __dojo_armed=1
    return $code
  fi
  __dojo_ran=0
  __dojo_armed=1

  h=$(HISTTIMEFORMAT= history 1 2>/dev/null)
  read -r num cmd <<< "$h"
  [ -z "$cmd" ] && return $code
  cmd=${cmd//$'\n'/ }
  cmd=${cmd//$'\x1f'/ }
  [ -z "$cmd" ] && return $code

  off=""
  [ -f "$DOJO_ERR" ] && off=$(stat -c %s "$DOJO_ERR" 2>/dev/null)

  printf '%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
    "${EPOCHSECONDS:-$(date +%s)}" "$code" "$PWD" "$cmd" "${off:-}" >> "$DOJO_CTX"

  # 太大就砍掉前面
  if [ "$(stat -c %s "$DOJO_CTX" 2>/dev/null || echo 0)" -gt 262144 ]; then
    tail -n 500 "$DOJO_CTX" > "$DOJO_CTX.tmp" 2>/dev/null && mv "$DOJO_CTX.tmp" "$DOJO_CTX"
  fi

  return $code
}

# 可选：整条 shell 的 stderr 落一份，dojo 才能看到具体报错
# 代价：stderr 不再是 tty，少数程序判断 isatty(2) 的行为会变
if [ -f "$HOME/.config/dojo/config.toml" ] \
   && grep -A8 '^\[context\]' "$HOME/.config/dojo/config.toml" 2>/dev/null | grep -q 'capture_stderr *= *true'; then
  # 太大就截断，别让日志无限长
  if [ -f "$DOJO_ERR" ] && [ "$(stat -c %s "$DOJO_ERR" 2>/dev/null || echo 0)" -gt 524288 ]; then
    tail -c 262144 "$DOJO_ERR" > "$DOJO_ERR.tmp" 2>/dev/null && mv "$DOJO_ERR.tmp" "$DOJO_ERR"
  fi
  : >> "$DOJO_ERR"
  exec 2> >(tee -a "$DOJO_ERR" >&2)
fi

if declare -p PROMPT_COMMAND 2>/dev/null | grep -q 'declare -a'; then
  case " ${PROMPT_COMMAND[*]} " in
    *" __dojo_hook "*) ;;
    *) PROMPT_COMMAND+=(__dojo_hook) ;;
  esac
else
  case ";${PROMPT_COMMAND:-};" in
    *";__dojo_hook;"*) ;;
    *) PROMPT_COMMAND="__dojo_hook${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
  esac
fi
