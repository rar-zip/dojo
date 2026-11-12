# dojo

装在你自己 Linux 上的终端陪练。

它看得见你敲的命令、退出码、目录，随时能问。默认只说话不动手；到了 L5 才允许代跑，而且一步一确认，跑前做快照，随时能停，默认回滚。

不是 agent。区别不在能力，在契约：

| | agent | dojo |
|---|---|---|
| 主体 | 给个目标，自己跑完 | 你操作，它陪 |
| 默认权限 | 默认可执行 | 默认只读，执行要点头 |
| 可见性 | 结果汇报 | 每一步实时 |
| 停止 | 中断任务 | 刹车 + 回滚，停得干净 |
| 成功标准 | 任务完成 | 你知道刚才发生了什么 |

dojo 不允许「无人值守」这个状态存在。

## 装

需要 Linux + bash/zsh + python3.11 以上。

源码：

```bash
git clone https://github.com/rar-zip/dojo.git ~/dojo
cd ~/dojo
./install.sh
```

或者一行（自包含安装器，不依赖仓库）：

```bash
wget -qO- https://raw.githubusercontent.com/rar-zip/dojo/main/dist/dojo-install.sh | bash
```

装完新开一个终端，`dojo doctor` 自检。

## 升级

一行装的，直接：

```bash
dojo upgrade
```

它会带进度条拉最新的安装脚本，问一句，然后覆盖 `~/.local/bin/dojo`，旧版备份在 `~/.local/state/dojo/backup/`

源码装的：`cd ~/dojo && git pull && ./install.sh`

拉不下来通常是 raw.githubusercontent.com 被墙，挂个代理再试，或者用源码那条路

## 用

```bash
dojo chat                   # 连着聊，问不清楚可以追问
dojo                        # 当前状态
dojo status                 # 详细状态
dojo ask "这报错啥意思"      # 问一句就走
dojo explain                # 解释上一条命令（带退出码和 stderr）
dojo run "把日志里 500 的行数出来"   # 说人话，它出方案，L5 下逐步确认执行
dojo exec "df -h"           # 直接跑一条字面命令（L5，仍要确认）
dojo acp                    # 当 ACP agent 跑，给编辑器当后端
dojo complete -p "grep -r TODO "   # FIM 补全，只吐补出来的那段
dojo preview "rm -rf build"  # 沙盒里先跑一遍，看完再决定应用还是丢弃
dojo undo                   # 撤掉最近一步
dojo undo all               # 撤掉最近一次运行的全部步骤
dojo history                # 看运行记录
dojo commands               # 看代跑过的每一条命令（统一日志）
dojo stop                   # 让正在跑的任务停手
dojo level 3                # 切协助等级
dojo log                    # 看它眼里的上下文
dojo doctor                 # 自检
dojo config get exec.ttl_days   # 看/改配置
dojo uninstall              # 干净卸载（--purge 连状态一起删）
```

## 聊天

`dojo chat` 是个常驻的对话，直接打字提问，接着上次的上下文继续，退出也不丢：

```
你> HTTP 是跑在什么上的
老王：TCP，80 和 443 那两个端口。HTTP/3 例外，底下是 UDP。
你> 那它跟 TCP 的区别一句话
老王：...
```

里面还有几条命令：`/run 想做的事` 让它出方案、`/exec 命令` 直接跑字面命令、`/undo` 撤销、`/level` 切等级、`/log` 看上下文、`/clear` 清空对话、`/exit` 退出

老王回话里如果带命令，L5 下会直接问你要不要跑，不用再打一遍 `dojo run`

## 协助等级

| 级 | 行为 |
|---|---|
| L1 | 旁观：只答不问，一句话 |
| L2 | 讲解：讲原理，不给命令 |
| L3 | 指路：给方向、关键词、man 页（默认） |
| L4 | 代笔：给完整命令，你自己敲 |
| L5 | 陪练：可以申请代跑，每条都要你点头 |

L5 下 `dojo run "想做的事"` 的流程：

1. 模型给出方案，命令放在代码块里，先全部打印出来
2. 逐条问：`Enter 跑 / e 改 / s 跳过 / q 退出`
3. 跑之前对这条命令会碰到的文件做快照
4. 跑的时候按 Ctrl+C 进「刹车」：命令还在跑，你选怎么停
5. 跑完可以接着说「还要改什么」，接着下一轮，不用重新起手

## 刹车与回滚

Ctrl+C 一次不会直接杀命令，先弹四个选项：

```
1) 就这样停：不再跑新步骤，这条命令让它跑完
2) 中断并回滚：杀掉这条命令，把这一步的修改撤掉（默认）
3) 撤掉整个任务：杀掉命令，这次运行做过的步骤全撤
4) 继续跑：当我没按过
```

15 秒不选，按 2 处理。`stop.ask = false` 可以关掉询问，直接中断回滚；`stop.timeout_seconds` 改倒计时。

回滚粒度：

- **文件类**：> >> cp mv rm sed -i tee chmod chown mkdir 等，跑前把目标复制一份，撤的时候还原（新建的文件直接删掉）
- 管道和 `&&` 会拆开逐段看，`cmd | tee f` 里的 f 也逃不掉
- `find ... -delete` 会先空跑一遍列出命中项，再逐个快照
- `xargs`、命令替换、`eval` 这种猜不准的，跑之前会明说撤不了，不装
- 解压、git、rsync 这类按性质整目录快照
- **系统类**：apt / systemctl / pip / docker / kill / useradd 这些做不了可靠快照，只给反向命令，不假装能撤
- 单个文件或目录超过 `exec.max_snapshot_mb`（默认 200MB）就不快照，并明确告诉你

说人话那个入口是 `dojo run`，`dojo exec` 才是跑字面命令，别搞混

## 沙盒预演（dojo preview）

快照靠的是「跑前把目标文件复制一份」，碰到复杂脚本、`git clean`、`make clean` 这种猜不准的，就只能整目录快照，或者明说撤不回来。

`dojo preview` 换了个思路：把当前目录套一层 overlayfs，命令在隔离层里跑，改完了先看清单，再决定应用还是丢掉。

```bash
dojo preview "rm -rf build && make"          # 跑完问你 1 应用 2 丢弃
dojo preview --apply "sed -i 's/a/b/' x.txt"  # 不问，直接应用
dojo preview --discard "..."                  # 不问，直接丢
```

跑完会列出 `新增 / 修改 / 删除` 清单，默认丢弃。丢弃的话真实文件一个字节都没动过。

前提和边界：

- 需要内核允许无特权用户命名空间（`unshare -Ur` 能跑），和 overlayfs 支持；现代发行版基本都有
- 只隔离**当前目录这一层**。写 `~/xxx`、`/tmp`、`/etc` 还是真写，别拿它试 `sudo rm -rf /`
- `apt`、`systemctl` 这种要 root 的，在沙盒里本来就跑不动，不是隔离问题
- 沙盒目录在 `~/.local/state/dojo/sandbox/`，跑完就删

`dojo undo` 默认撤最近一步，`dojo undo all` 撤最近一次运行的全部步骤。

## 缺 root 权限怎么办

装包、改系统配置这类活，普通用户跑必然 `Permission denied`。dojo 不会假装没看见，也不会自作主张提权：

- 预案里出现 `apt` / `systemctl` / `useradd` 这类需要 root 的命令，而你还没加 sudo，跑之前先问一句「要我加上 sudo 吗」
- 如果命令跑挂了，输出里出现 `Permission denied` / `are you root` 这类，会再问「要我加 sudo 重跑这一步吗」
- 默认都是拒绝（只有提前那句是 Y），你说 y 才动

提权这一步会按系统级操作处理：做不了可靠快照，`undo` 撤不回来，跑之前会明说。

不想被问就 `dojo config set exec.offer_sudo false`。

## 接编辑器（ACP）

dojo 能把自己包成 ACP agent，编辑器通过 stdio 上的 JSON-RPC 连过来。Zed 这类支持 ACP 的客户端，配置里加一段：

```json
{
  "agent_servers": {
    "dojo": { "command": "dojo", "args": ["acp"] }
  }
}
```

实现了 `initialize`、`authenticate`、`session/new`、`session/prompt`、`session/cancel`，回答按 `session/update` 流式回包。**它只负责说话**：不接文件读写、不接终端控制，所以编辑器那边不会因为 dojo 自动改了什么。

## 补全（FIM）

```bash
dojo complete -p "grep -r TODO "
printf '%s\0%s' "前半段" "后半段" | dojo complete
```

走 DeepSeek 的 `/beta/completions`（FIM），只输出补出来的那一段，不加换行，方便 shell 的补全部件或编辑器直接吃。`-n 64` 控制长度。

## 安全红线

有些东西它不替你碰，也不替你撤：

- `rm -rf /`、`rm -rf ~`、`mkfs`、`fdisk`、fork 炸弹直接拒绝，不是弹窗，是根本不跑
- 目标落在 `/etc`、`/boot`、`/usr`、`/var/lib`、`/sys`、`/proc` 的写删操作，按 `safety.deny_paths` 硬拦
- 高风险删除、`dd`、`shred` 会在跑之前提示，`safety.require_typed_confirm = true` 时还要手打「确认」
- 命令和对话里像 `sk-...`、`password=...`、`Bearer ...` 的东西，写日志和存档前会打码
- 单步执行超过 `exec.max_step_seconds`（默认 600 秒）自动中断并回滚

## 配置

`~/.config/dojo/config.toml`（600）

```toml
[model]
base_url = "https://api.deepseek.com/v1"   # 任意 OpenAI 兼容接口
model = "deepseek-flash"
api_key = ""                                # 也可以 DEEPSEEK_API_KEY / DOJO_API_KEY
stream = true
timeout_seconds = 90

[assist]
level = 3

[context]
history = 8
capture_stderr = true

[exec]
max_snapshot_mb = 200
max_step_seconds = 600
ttl_days = 7
capture_output = true      # 代跑的输出存一份，dojo log 能回看
output_max_kb = 512        # 超过就砍一半

[safety]
redact_secrets = true
deny_paths = ["/etc", "/boot", "/usr", "/var/lib", "/sys", "/proc"]
require_typed_confirm = false

[stop]
ask = true
timeout_seconds = 15
```

### 报错怎么答

空敲 `dojo` 时，失败的那条会在终端里被摊成三行：

```
原因  127 就是 shell 找不到这个命令，八成是名字打错了
猜测  你大概是想试某个命令，把占位符当真命令敲了
方案  1. command -v notacommand || echo 没有这个命令
      2. type -a notacommand; echo $PATH
```

方案那几行就是能直接粘进终端的命令，不是让你自己翻译的文字。

方案都不对，直接说目的，让它重新算：

```bash
dojo why "我想看哪个进程占了 80 端口"
```

它会带着刚才挂掉的命令和你的目的重新算一份，不再猜偏。

方案看着对，敲个数字就能跑，不用复制粘贴：

```bash
dojo 1      # 跑上一张卡片的第一条方案
dojo 3      # 第三条
```

走的是正常代跑链路，跑前有快照，出问题 `dojo undo` 一样能撤。

撤之前想先看看改了哪几行：

```bash
dojo diff            # 最近一次运行
dojo diff 20261112-201530-...
```

### Ctrl-G 行内补全

装完 hook 之后，命令敲到一半按 `Ctrl-G`，它会把光标前后文丢给 `dojo complete`，补出来的直接塞回光标处。想换键位，改 `lib/hook.bash` 里的 `bind -x` 或 `lib/hook.zsh` 里的 `bindkey` 那一行就行。

### auto_explain

默认开。空敲 `dojo` 时，如果上一条命令是失败的（退出码非 0，且在一小时内），它不打印状态，直接告诉你为什么挂、先看哪里。不想被它主动搭话就 `dojo config set context.auto_explain false`。

### capture_stderr

默认开。shell 启动时给 stderr 接一对 PTY：数据照旧显示在终端、`isatty(2)` 仍然是真（颜色不丢），同时留一份到 `~/.local/state/dojo/stderr.log`，`dojo explain` 就能看到真正的报错。

多了一个后台转发进程，退出 shell 自己会走。不想开就 `dojo config set context.capture_stderr false`。

### capture_output

默认开。`dojo run` / `dojo exec` 每次代跑都开 PTY，输出同时显示在终端并存进该次运行的 `output.log`（保留颜色和 `isatty`），`dojo log` 会带出最近一次输出的尾部。

不想存就 `dojo config set exec.capture_output false`。

## 它看到什么

- 最近 N 条命令（默认 8）、退出码、当时目录
- 上一条命令的 stderr（仅当 `capture_stderr = true`）
- 当前协助等级

看不到：屏幕内容、文件内容（除非你把内容贴进问题里）、别的终端。

命令记录由 shell hook 完成。bash 和 zsh 都支持，装的时候按 `$SHELL` 自动选。

## 它做不到什么

- 需要交互输入的命令（sudo 密码、vim、top 这类全屏 TUI）不适合代跑，dojo 只跑非交互命令
- `apt` / `systemctl` 这类系统级操作撤不回来，只能给反向命令
- 不接管你的 shell，退出 dojo 进程就结束，没有后台常驻

## 卸载

```bash
rm -f ~/.local/bin/dojo
# 删掉 shell 配置里 # >>> dojo >>> 到 # <<< dojo <<< 之间的块
rm -rf ~/.config/dojo ~/.local/state/dojo ~/.local/share/dojo
```

## 命令都记在哪

L5 代跑过的每一条命令都会追加到 `~/.local/state/dojo/commands.log`，带时间、运行 ID、第几步、退出码：

```
2026-11-10 21:14:54  run=20261110-211454-468407  #1/1  rc=0  echo one > a.txt
```

`dojo commands` 看最近 20 条，`dojo commands 100` 看更多。日志只留最近两千行，不会无限长。

## 开发

```bash
python3 -W error tests/test_core.py   # 76 个用例：解析 / 快照 / 回滚 / CLI / ACP / hook
python3 tools/build_installer.py   # 生成 dist/dojo-install.sh
```

目录：

```
bin/dojo              主程序（单文件 python）
lib/hook.bash         bash 命令记录
lib/hook.zsh          zsh 命令记录
install.sh            源码安装
tools/build_installer.py  打一行安装器
tests/test_core.py    回归测试
docs/技术方案.md       设计与「停」的语义
docs/路线图-v0.7-v1.0.md  接下来几版怎么走
```

## 路线

已经落地的：

- [x] P1 只看只说，流式回答
- [x] P2 L5 代跑，一步一确认，Ctrl+C 刹车
- [x] P3 快照 / undo / 系统级操作分级
- [x] P4 PTY 报错捕获、空敲直答（原因 / 猜测 / 方案）
- [x] P5 OverlayFS 沙盒预演
- [x] P6 ACP 编辑器接入、FIM 补全
- [x] v0.7 交互手感闭环：`dojo 1/2/3` 选号执行、`dojo diff`、Ctrl-G 行内补全

接下来，不往重型全自动 Agent 方向膨胀，守住「你是司机、它是副驾，零第三方依赖、无常驻进程」：

- **v0.8 快照与沙盒双网合一**：静态猜不准影响面时主动提议进沙盒；沙盒应用改动前自动转存为标准快照，应用完也能 `dojo undo`
- **v0.9 视野精准扩展**：ACP 模式下共享终端报错现场；报错里出现本地文件行号时，受控摘取上下几行（脱敏、排除 deny_paths）
- **v1.0 工程结构升级**：开发态拆到 `src/dojo/`，分发态仍由构建脚本拼成单文件，对外还是 `wget | bash`

细节在 [docs/路线图-v0.7-v1.0.md](docs/路线图-v0.7-v1.0.md)。

## License

MIT
