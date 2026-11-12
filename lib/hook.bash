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

# 可选：把这条 shell 的 stderr 落一份日志，dojo 才能看到具体报错
# 用 python 开一对 PTY，把 slave 接到 fd 2：写出去的仍是终端（有颜色、isatty(2) 为真），
# 另一头由后台进程转发到真实 tty 并记进 stderr.log
DOJO_CFG="${DOJO_CONFIG:-$HOME/.config/dojo/config.toml}"
# 默认开：只有配置里显式写了 capture_stderr = false 才关
if [ -f "$DOJO_CFG" ] \
   && ! grep -A8 '^\[context\]' "$DOJO_CFG" 2>/dev/null | grep -q 'capture_stderr *= *false'; then
  # 太大就截断，别让日志无限长
  if [ -f "$DOJO_ERR" ] && [ "$(stat -c %s "$DOJO_ERR" 2>/dev/null || echo 0)" -gt 524288 ]; then
    tail -c 262144 "$DOJO_ERR" > "$DOJO_ERR.tmp" 2>/dev/null && mv "$DOJO_ERR.tmp" "$DOJO_ERR"
  fi
  __dojo_slave=$(python3 - "$DOJO_ERR" <<'PY' 2>/dev/null
import fcntl, os, pty, re, sys, termios

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
    pending = b""
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
            # 外层终端还会再转一次 \n，把多于一个的 \r 压掉，免得出 \r\r\n。
            # \r 和 \n 可能被拆到两次 read 里，所以先攒住结尾的 \r
            chunk = pending + data
            tail = re.search(rb"\r+$", chunk)
            if tail:
                pending = chunk[tail.start():]
                chunk = chunk[:tail.start()]
            else:
                pending = b""
            chunk = re.sub(rb"\r+\n", b"\n", chunk)
            try:
                if chunk:
                    os.write(tty, chunk)
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
