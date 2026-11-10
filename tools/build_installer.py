#!/usr/bin/env python3
"""把 bin/dojo 和 shell hook 打包成可 wget|bash 的单文件安装器"""
import base64
import os

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "dist", "dojo-install.sh")

TEMPLATE = r'''#!/usr/bin/env bash
# dojo 一行安装器 v0.1
# 用法： wget -qO- <这个文件的地址> | bash
set -euo pipefail

say() { printf '%s\n' "$*"; }

BIN_DIR="$HOME/.local/bin"
SHARE_DIR="$HOME/.local/share/dojo"
CONF_DIR="$HOME/.config/dojo"
STATE_DIR="$HOME/.local/state/dojo"
CONF="$CONF_DIR/config.toml"

command -v python3 >/dev/null 2>&1 || { say "dojo 需要 python3（3.11 以上），先装上"; exit 1; }
if ! python3 -c 'import tomllib' >/dev/null 2>&1; then
  say "python3 版本太老，缺 tomllib，要 3.11 以上"
  python3 -V || true
  exit 1
fi

mkdir -p "$BIN_DIR" "$SHARE_DIR" "$CONF_DIR" "$STATE_DIR"
chmod 700 "$STATE_DIR"

base64 -d > "$BIN_DIR/dojo" <<'__DOJO_B64__'
__DOJO_PAYLOAD__
__DOJO_B64__
chmod +x "$BIN_DIR/dojo"

base64 -d > "$SHARE_DIR/hook.bash" <<'__HOOK_B64__'
__HOOK_PAYLOAD__
__HOOK_B64__

base64 -d > "$SHARE_DIR/hook.zsh" <<'__ZHOOK_B64__'
__ZHOOK_PAYLOAD__
__ZHOOK_B64__

if [ ! -f "$CONF" ]; then
  KEY=""
  if [ -f "$HOME/.openclaw/openclaw.json" ]; then
    KEY=$(python3 - <<'__KEY_PY__' 2>/dev/null || true
import json, os
p = os.path.expanduser("~/.openclaw/openclaw.json")
try:
    print(json.load(open(p))["models"]["providers"]["deepseek"]["apiKey"])
except Exception:
    pass
__KEY_PY__
)
  fi
  {
    printf '%s\n' '[model]'
    printf '%s\n' 'base_url = "https://api.deepseek.com/v1"'
    printf '%s\n' 'model = "deepseek-flash"'
    printf 'api_key = "%s"\n' "$KEY"
    printf '%s\n' 'stream = true'
    printf '%s\n' ''
    printf '%s\n' '[assist]'
    printf '%s\n' 'level = 3'
    printf '%s\n' ''
    printf '%s\n' '[context]'
    printf '%s\n' 'history = 8'
    printf '%s\n' 'capture_stderr = false'
    printf '%s\n' ''
    printf '%s\n' '[exec]'
    printf '%s\n' 'max_snapshot_mb = 200'
    printf '%s\n' ''
    printf '%s\n' '[stop]'
    printf '%s\n' 'ask = true'
    printf '%s\n' 'timeout_seconds = 15'
    printf '%s\n' ''
    printf '%s\n' '[persona]'
    printf '%s\n' 'name = "老王"'
  } > "$CONF"
  chmod 600 "$CONF"
  say "配置写到 $CONF"
fi

# shell hook：按当前 shell 选 rc
case "$(basename "${SHELL:-bash}")" in
  zsh) RC="$HOME/.zshrc"; HOOK="$SHARE_DIR/hook.zsh" ;;
  *)   RC="$HOME/.bashrc"; HOOK="$SHARE_DIR/hook.bash" ;;
esac
if ! grep -q '>>> dojo >>>' "$RC" 2>/dev/null; then
  {
    printf '\n%s\n' '# >>> dojo >>>'
    printf '[ -f "%s" ] && . "%s"\n' "$HOOK" "$HOOK"
    printf '%s\n' 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac'
    printf '%s\n' '# <<< dojo <<<'
  } >> "$RC"
  say "shell hook 已写进 $RC"
fi

if ! grep -q 'api_key = "[^"]' "$CONF" 2>/dev/null && [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  say ""
  say "提醒：还没配 API key。"
  say "  编辑 $CONF 填 [model] 里的 api_key，或者 export DEEPSEEK_API_KEY=sk-..."
fi

say ""
say "装好了。新开一个终端，或者 source $RC"
say "然后敲 dojo doctor 自检，dojo ask \"问题\" 开问"
'''


def main():
    dojo = base64.b64encode(open(os.path.join(REPO, "bin", "dojo"), "rb").read()).decode()
    hook = base64.b64encode(open(os.path.join(REPO, "lib", "hook.bash"), "rb").read()).decode()
    zhook = base64.b64encode(open(os.path.join(REPO, "lib", "hook.zsh"), "rb").read()).decode()
    text = (
        TEMPLATE.replace("__DOJO_PAYLOAD__", dojo)
        .replace("__HOOK_PAYLOAD__", hook)
        .replace("__ZHOOK_PAYLOAD__", zhook)
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(text)
    os.chmod(OUT, 0o755)
    print(f"生成 {OUT}  ({len(text)} 字节)")


if __name__ == "__main__":
    main()
