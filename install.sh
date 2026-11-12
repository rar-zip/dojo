#!/usr/bin/env bash
# dojo v0.1 安装脚本（源码版）
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONF_DIR="$HOME/.config/dojo"
STATE_DIR="$HOME/.local/state/dojo"
CONF="$CONF_DIR/config.toml"

say() { printf '%s\n' "$*"; }

# 1. python
if ! command -v python3 >/dev/null; then
  say "需要 python3（3.11 以上），先装一下"
  exit 1
fi
if ! python3 -c 'import tomllib' 2>/dev/null; then
  say "python3 版本太老，缺 tomllib，要 3.11 以上"
  python3 -V
  exit 1
fi

# 2. 目录和命令
mkdir -p "$BIN_DIR" "$CONF_DIR" "$STATE_DIR"
chmod 700 "$STATE_DIR"
ln -sfn "$REPO/bin/dojo" "$BIN_DIR/dojo"
chmod +x "$REPO/bin/dojo" "$REPO/lib/hook.bash" "$REPO/lib/hook.zsh"
say "命令装到 $BIN_DIR/dojo"

# 3. 配置
if [ ! -f "$CONF" ]; then
  KEY=""
  if [ -f "$HOME/.openclaw/openclaw.json" ]; then
    KEY=$(python3 - <<'PY' 2>/dev/null || true
import json, os
p = os.path.expanduser("~/.openclaw/openclaw.json")
try:
    print(json.load(open(p))["models"]["providers"]["deepseek"]["apiKey"])
except Exception:
    pass
PY
)
  fi
  cat > "$CONF" <<EOF
[model]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-flash"
api_key = "$KEY"
stream = true

[assist]
level = 3

[context]
history = 8
capture_stderr = true

[exec]
max_snapshot_mb = 200

[stop]
ask = true
timeout_seconds = 15

[persona]
name = "老王"
EOF
  chmod 600 "$CONF"
  say "配置写到 $CONF"
  [ -n "$KEY" ] && say "已经借用本机 openclaw 的 DeepSeek key"
else
  say "配置已存在，不动它：$CONF"
fi

# 4. shell hook（bash / zsh）
"$BIN_DIR/dojo" init

# 5. 提示
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "提醒：$BIN_DIR 不在 PATH 里，把 export PATH=\"\$HOME/.local/bin:\$PATH\" 加进 shell 配置" ;;
esac

say ""
say "装好了。新开一个终端，或者 source 一下 shell 配置"
say "然后敲 dojo doctor 自检，dojo ask \"问题\" 开问"
say "想让它代跑：dojo level 5，然后 dojo run \"想做的事\""
