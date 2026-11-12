# dojo shell hook（zsh）
# 由 ~/.zshrc 里 # >>> dojo >>> 标记块 source 进来

[[ -o interactive ]] || return 0

DOJO_STATE_DIR="${DOJO_STATE_DIR:-$HOME/.local/state/dojo}"
DOJO_CTX="$DOJO_STATE_DIR/ctx.tsv"
DOJO_ERR="$DOJO_STATE_DIR/stderr.log"
mkdir -p "$DOJO_STATE_DIR" 2>/dev/null

__dojo_last_num=""

__dojo_hook() {
  local code=$? cmd off num

  # 用历史编号去重，别用命令内容，不然连着敲两条一样的，第二条会被吞
  num=${HISTCMD:-}
  if [ -n "$num" ] && [ "$num" = "$__dojo_last_num" ]; then
    return $code
  fi

  cmd=$(fc -ln -1 2>/dev/null | sed 's/^[[:space:]]*//')
  [ -z "$cmd" ] && return $code
  __dojo_last_num=$num

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

DOJO_CFG="${DOJO_CONFIG:-$HOME/.config/dojo/config.toml}"
# 默认开：只有配置里显式写了 capture_stderr = false 才关
if [ -f "$DOJO_CFG" ] \
   && ! grep -A8 '^\[context\]' "$DOJO_CFG" 2>/dev/null | grep -q 'capture_stderr *= *false'; then
  if [ -f "$DOJO_ERR" ] && [ "$(stat -c %s "$DOJO_ERR" 2>/dev/null || echo 0)" -gt 524288 ]; then
    tail -c 262144 "$DOJO_ERR" > "$DOJO_ERR.tmp" 2>/dev/null && mv "$DOJO_ERR.tmp" "$DOJO_ERR"
  fi
  __dojo_slave=$(python3 - "$DOJO_ERR" <<'PY' 2>/dev/null
import fcntl, os, pty, sys, termios

log = sys.argv[1]
os.makedirs(os.path.dirname(log), exist_ok=True)
master, slave = pty.openpty()
try:
    fd = os.open("/dev/tty", os.O_RDONLY)
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    finally:
        os.close(fd)
except OSError:
    pass
# setsid 之后就没有控制终端了，/dev/tty 必然 ENXIO，必须在 fork 前先抓住它
try:
    fwd = os.open("/dev/tty", os.O_WRONLY)
except OSError:
    try:
        fwd = os.dup(2)  # 这时 fd2 还连着真终端
    except OSError:
        fwd = None
# slave 关掉 OPOST：否则 \n 先被换成 \r\n，转发到外层终端再换一次，出现 \r\r\n
try:
    attrs = termios.tcgetattr(slave)
    attrs[1] &= ~termios.OPOST
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
except (OSError, termios.error):
    pass
path = os.ttyname(slave)
if os.fork() == 0:
    try:
        os.setsid()
    except OSError:
        pass
    if os.fork() > 0:
        os._exit(0)
    import threading
    # 别攥着命令替换的管道，不然 $(...) 永远等不到 EOF
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    os.close(devnull)
    # 先替 shell 攥着 slave，2 秒后放开；否则 /dev/pts/N 在 exec 2> 之前就消失了
    threading.Timer(2.0, lambda: os.close(slave)).start()
    tty = fwd
    lf = open(log, "ab", buffering=0)
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        try:
            lf.write(data)
        except OSError:
            pass
        if tty is not None:
            try:
                os.write(tty, data)
            except OSError:
                tty = None
    os._exit(0)
print(path)
PY
)
  if [ -n "$__dojo_slave" ] && [ -e "$__dojo_slave" ]; then
    exec 2>"$__dojo_slave"
  fi
  unset __dojo_slave
fi

autoload -Uz add-zsh-hook 2>/dev/null
if command -v add-zsh-hook >/dev/null 2>&1; then
  add-zsh-hook precmd __dojo_hook
else
  precmd_functions+=(__dojo_hook)
fi
