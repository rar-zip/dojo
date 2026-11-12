# dojo

**面向 Linux 终端的受控 AI 陪练与交互式诊断工具（Human-in-the-Loop Terminal Copilot）**

[![Version](https://img.shields.io/github/v/release/rar-zip/dojo)](https://github.com/rar-zip/dojo/releases)
[![License](https://img.shields.io/github/license/rar-zip/dojo)](https://github.com/rar-zip/dojo/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/rar-zip/dojo)

[**`dojo`**](https://github.com/rar-zip/dojo) 是一个运行在本地 Linux 环境下的零依赖终端陪练工具。它通过轻量级 Shell Hook 实时感知你在终端中执行的命令、退出码、工作目录与标准错误输出（`stderr`），在你遇到报错或卡壳时按需提供诊断、思路或可执行方案。

**核心设计原则：你是司机，它是副驾。`dojo` 严禁“无人值守”的自动执行状态。** 默认级别下它只读只说、绝不动手；仅在最高协助等级（L5）下才允许申请代跑命令，且严格遵循**“一步一确认、跑前做快照、中途可刹车、默认能回滚”**的安全契约。

## 为什么是 `dojo` 而不是 Agent？

`dojo` 与自主型 Agent 的本质区别不在模型能力，而在**人机控制权契约**：

| 维度 | 自主型 Agent | `dojo` 终端陪练 |
| :--- | :--- | :--- |
| **操作主体** | 用户下达目标，Agent 自主规划并跑完全程 | 用户主导操作，AI 在旁实时观察与辅助 |
| **默认权限** | 默认具备命令执行与文件读写权限 | 默认纯只读（L1–L4），仅 L5 允许逐条点头代跑 |
| **执行可见性** | 过程黑盒或事后汇总汇报 | 全程绑定当前 PTY 终端，每一步实时流式可见 |
| **中断与停止** | 强制杀死进程，常遗留半成品脏现场 | **Ctrl+C 柔性刹车** + 自动快照回滚，确保现场干净 |
| **系统架构** | 依赖复杂的运行时框架、容器或常驻守护进程 | **单文件 Python 标准库实现**，零第三方依赖，退出即终止 |
| **成功标准** | 任务结果跑通 | 系统状态可控，且你清楚刚才发生了什么 |

## 核心特性

- **报错空敲直答**：当上一条终端命令执行失败（退出码非 `0` 且在 1 小时内），直接在终端空敲 `dojo`，即可输出结构化的 **原因 / 猜测 / 可直接粘贴的修复方案**；若方案偏离预期，可通过 `dojo why "真实目的"` 携带报错现场重新生成。
- **方案选号直接跑（`dojo 1` / `2` / `3`）**：报错卡片里的三条方案会存成 `last_card.json`，敲个数字就能跑第 N 条，走正常代跑链路，跑前照样有快照，`dojo undo` 照常能撤。
- **`dojo diff` 回滚前预览**：拿 `runs/<id>/steps/` 的备份与当前工作区做 unified diff，撤之前先看清到底改了哪几行；目录快照逐个文件比，二进制自动跳过。
- **保真 PTY 报错捕获**：Shell Hook 通过独立伪终端（PTY）桥接 `stderr`，在完整记录报错日志供 AI 诊断的同时，保持 `isatty(2)` 为真，**不破坏任何命令行工具的彩色输出与终端宽度感知**。
- **Ctrl-G 行内补全**：装完 hook 之后，命令敲到一半按 `Ctrl-G`，把光标前后文丢给 `dojo complete`，补出来的片段直接塞回光标处（bash 用 `bind -x`，zsh 用 `zle`）。
- **L1–L5 五级渐进式协助**：从“一句话点拨（L1）”、“原理讲解（L2）”、“指路与 man 页索引（L3）”、“代写命令（L4）”到“受控代跑（L5）”，按需切换介入深度。
- **跑前快照与 SHA-256 校验回滚**：L5 代跑前自动解析命令影响面，对目标文件、目录、软链接及权限位创建快照；支持 `dojo undo` 单步撤销与 `dojo undo all` 全任务回滚，并校验还原后的文件 SHA-256 摘要。
- **OverlayFS 无痕沙盒预演（`dojo preview`）**：基于 Linux 无特权用户命名空间（`unshare`）与 `overlayfs` 将当前目录挂载为隔离层，先在沙盒中运行复杂脚本或清理命令，审阅完 `新增 / 修改 / 删除` 差异清单后再决定应用或丢弃。
- **智能提权协商（`offer_sudo`）**：识别需 `root` 权限的系统命令或在捕获到 `Permission denied` 时主动询问是否包装 `sudo` 重试，绝不自作主张提权。
- **多层安全红线与密钥脱敏**：内置策略引擎硬性拦截删根、磁盘格式化、Fork 炸弹及 `/etc`、`/boot`、`/usr` 等受保护目录的写删操作；所有命令记录、日志与发往模型的上下文自动脱敏 `sk-*`、`Bearer`、`password=` 等敏感凭据。
- **编辑器集成（ACP）与行内补全（FIM）**：内置符合 JSON-RPC 2.0 规范的 `dojo acp`（stdio 模式）供 Zed 等编辑器作为只读后端接入；提供 `dojo complete` 对接 DeepSeek FIM 接口实现命令行片段补全。

## 快速安装

### 环境要求

- **操作系统**：Linux（支持 `bash` 或 `zsh`）
- **运行时**：Python `>= 3.11`（仅使用内置标准库 `tomllib`、`pty`、`urllib` 等，无需 `pip` 安装任何第三方包）

### 方式一：单文件一键安装（推荐）

无需克隆仓库，直接拉取自包含安装脚本 [dist/dojo-install.sh](https://raw.githubusercontent.com/rar-zip/dojo/main/dist/dojo-install.sh)：

```bash
wget -qO- https://raw.githubusercontent.com/rar-zip/dojo/main/dist/dojo-install.sh | bash
```

### 方式二：源码安装

```bash
git clone https://github.com/rar-zip/dojo.git ~/dojo
cd ~/dojo
./install.sh
```

安装完成后，重新打开一个终端或执行 `source ~/.bashrc`（Zsh 用户执行 `source ~/.zshrc`），运行自检命令确认环境就绪：

```bash
dojo doctor
```

### 版本升级与卸载

```bash
dojo upgrade           # 一键拉取最新安装器并升级（旧版本自动备份至 ~/.local/state/dojo/backup/）
dojo uninstall         # 移除二进制软链与 Shell Hook 配置块
dojo uninstall --purge # 彻底卸载并清除 ~/.config/dojo 与 ~/.local/state/dojo 全部数据
```

## 命令速查手册

| 命令格式 | 功能说明 | 权限要求 |
| :--- | :--- | :--- |
| `dojo` | **智能入口**：若上一条命令失败（1 小时内）则直接诊断报错；否则展示当前状态摘要 | 只读 |
| `dojo 1` / `2` / `3` | **方案选号执行**：直接跑上一张报错卡片里的第 N 条方案 | 需 **L5** |
| `dojo diff [ID]` | **回滚前预览**：对比指定运行（默认最近一次）的快照与当前工作区，打印 unified diff | 只读 |
| `dojo status` | 强制查看版本、协助等级、模型配置、沙盒可用性及最近命令记录 | 只读 |
| `dojo why "真实目的"` | 当默认报错方案不符合预期时，携带刚挂掉的命令现场与你的真实意图重新生成方案 | 只读 |
| `dojo errors [N]` | 列出最近 `N` 条（默认 10 条）执行失败的命令、时间及退出码 | 只读 |
| `dojo chat` | 启动持久化多轮对话（保留最近上下文，支持 `/run`、`/exec`、`/undo` 等内联指令） | 默认只读（内联执行需 L5） |
| `dojo ask "问题"` | 单次快速提问，流式返回解答后立即退出 | 只读 |
| `dojo explain` | 结合最近命令序列、退出码与 `stderr` 详细解释上一条命令发生了什么 | 只读 |
| `dojo run "需求描述"` | **自然语言任务规划**：由模型生成完整命令方案并在 L5 下逐条确认代跑，支持多轮跟进直至 `DONE` | 规划只读，代跑需 **L5** |
| `dojo exec "字面命令"` | **字面命令受控代跑**：跳过模型规划，在跑前快照、策略检查与刹车保护下直接执行指定命令 | 需 **L5** |
| `dojo preview "命令"` | **沙盒无痕预演**：在 `overlayfs` 隔离层中试跑命令，展示文件变更清单后再决定 `--apply` 或 `--discard` | 需 **L5** |
| `dojo undo [ID] [N\|all]` | 回滚最近一步（默认）、最近 `N` 步、整次运行（`all`）或指定历史运行 ID 的文件修改 | 本地恢复 |
| `dojo stop [--abort]` | 跨终端向正在运行的任务发送停止请求（加 `--abort` 立即向执行进程发送 `SIGINT` 触发刹车） | 本地控制 |
| `dojo history [N]` | 查看历次 L5 代跑的运行记录、步骤数与回滚状态 | 只读 |
| `dojo commands [N]` | 查看所有被代跑命令的统一审计日志（`~/.local/state/dojo/commands.log`） | 只读 |
| `dojo level [1-5]` | 查看或持久化切换默认协助等级 | 配置修改 |
| `dojo config [get\|set]` | 查看脱敏后的全量配置，或读写指定配置项（如 `dojo config set context.auto_explain false`） | 配置修改 |
| `dojo complete -p "前缀"` | 调用 FIM 接口补全命令或代码片段（支持 `-s "后缀"` 或通过 `stdin` 以 `\0` 分隔传入前后文） | 只读 |
| `dojo acp` | 以 ACP（Agent Control Protocol）stdio JSON-RPC 2.0 模式启动，供编辑器作为只读 AI 后端接入 | 只读 |
| `dojo log` | 查看 `dojo` 当前感知到的终端命令上下文、上一条 `stderr` 及最近一次代跑输出尾部 | 只读 |
| `dojo doctor` | 检查 Python 版本、配置文件、API Key、Shell Hook 注入状态及快照目录写权限 | 只读 |

## 核心工作流详解

### 1. 报错空敲直答、`dojo why` 与选号执行

当你在终端敲错命令或程序异常退出时，无需手打问题，直接敲 `dojo` 回车：

```text
$ notacommand --foo
bash: notacommand: command not found

$ dojo
上一条命令挂了（退出码 127）：notacommand --foo

原因  127 代表 shell 在 PATH 中找不到该可执行文件，通常是命令名拼写错误或软件包未安装
猜测  你想测试某个 CLI 工具是否在当前环境中可用
方案  1. command -v notacommand || echo "未找到该命令"
      2. echo "$PATH" | tr ':' '\n'
      直接跑：dojo 1（备选 dojo 2 / dojo 3），跑前照样有快照
```

如果三条猜测都不符合本意，直接补一句真实意图：

```bash
dojo why "我想查看当前是哪个进程占用了 8080 端口"
```

看着某条顺眼，敲数字就能跑，不用复制粘贴：

```bash
dojo 1     # 跑上一张卡片的第一条方案
dojo 3     # 第三条
```

跑的仍然是正常代跑链路，跑前有快照，出问题 `dojo undo` 一样能撤。撤之前想先看改了哪几行：

```bash
dojo diff              # 最近一次
dojo diff 20261112-201530-...
```

### 2. 五级协助等级（L1–L5）

通过 `dojo level <1-5>` 随时切换陪练介入程度：

| 等级 | 名称 | 行为边界与适用场景 | 允许代跑 |
| :--- | :--- | :--- | :---: |
| **L1** | 旁观 | 仅在被提问时用一句话极简作答，不主动展开，不给命令 | 否 |
| **L2** | 讲解 | 阐述现象背后的 Linux 机制与原理，提供排查关键词，不直接给现成命令 | 否 |
| **L3** | 指路 | **默认等级**。给出排查方向、关键参数与对应的 `man` 手册章节，培养独立操作手感 | 否 |
| **L4** | 代笔 | 给出完整可直接复制的命令，但明确要求由你自己敲入终端 | 否 |
| **L5** | 陪练 | 允许申请代跑命令：逐条确认、跑前自动快照、支持 Ctrl+C 刹车与一键回滚 | **是** |

### 3. L5 受控代跑、Ctrl+C 柔性刹车与智能回滚

在 L5 等级下执行 `dojo run "需求"` 时，`dojo` 会要求模型一次性给出从现状检查、变更执行到结果验证的完整命令序列（若模型仅给出 `cat`/`uname` 等纯只读侦察命令，会被自动打回要求补齐后续步骤）：

1. **逐条审批**：每一步执行前询问 `Enter 跑 / e 改 / s 跳过 / q 退出`。
2. **智能提权询问**：若检测到 `apt`、`systemctl` 等需 root 权限的命令未加 `sudo`，或执行后输出包含 `Permission denied`，会主动询问是否使用 `sudo -- bash --noprofile --norc -c` 包装重跑。
3. **Ctrl+C 柔性刹车**：在命令运行期间按下 `Ctrl+C`，**不会当场粗暴砍断进程留下半截脏现场**，而是由后台线程继续泵出 PTY 缓冲，同时弹出 4 选 1 刹车菜单（15 秒无操作或连按第二次 `Ctrl+C` 默认执行选项 `2`）：

```text
[刹车] 命令还在跑，先别急着走。
 1) 就这样停：不再跑新步骤，这条命令让它跑完
 2) 中断并回滚：杀掉这条命令，把这一步的修改撤掉（默认）
 3) 撤掉整个任务：杀掉命令，把这次运行做过的步骤全撤了
 4) 继续跑：当我没按过
```

**快照与回滚覆盖边界**：

- **精确文件级快照**：自动解析重定向（`>`、`>>`）、管道中的 `tee` 以及 `cp`、`mv`、`rm`、`ln`、`sed -i`、`chmod`、`chown`、`mkdir`、`touch`、`truncate`、`dd` 等操作的目标路径，备份原文件、软链接目标、权限位并计算 `SHA-256` 校验和；对于 `mkdir -p a/b/c` 等多级新建目录，自动追踪最顶层不存在的父目录，回滚时彻底清理不留空壳。
- **预演枚举快照**：针对 `find ... -delete`，在跑前自动通过 `find ... -print0` 预演列出命中文件（上限 500 项）并逐一快照。
- **整目录兜底快照**：针对 `tar`、`unzip`、`git`、`rsync`、`patch` 等难以静态推断具体产出文件名的写入型命令，自动对当前工作目录执行整目录快照（受 `exec.max_snapshot_mb` 限制，默认 200MB）。
- **动态参数透明告警**：针对包含命令替换 `$()`、反引号、管道 `xargs` 或 `eval` 的命令，在跑前明确告知无法静态预测目标路径，绝不伪造安全感。
- **系统级操作反向建议**：针对 `apt`、`dnf`、`pacman`、`systemctl`、`pip`、`npm`、`docker`、`useradd`、`ufw` 等系统级不可逆操作，跑前明确标注无法通过文件拷贝回滚，并在回滚时生成对应的反向恢复命令（如 `sudo apt remove <pkg>`、`sudo systemctl stop <svc>`）。

### 4. OverlayFS 沙盒预演（`dojo preview`）

当面对复杂构建脚本、`make clean` 或不确定影响范围的批量替换时，可使用 `dojo preview` 在内核级 `overlayfs` 隔离层中先行试跑：

```bash
dojo preview "rm -rf build && sed -i 's/foo/bar/g' src/*.conf"
dojo preview --apply "patch -p1 < fix.patch"   # 跑完免确认直接合并回真实目录
dojo preview --discard "rm -rf *"              # 仅观察输出与改动清单，跑完直接丢弃
```

沙盒仅隔离当前工作目录（`upperdir` 位于 `~/.local/state/dojo/sandbox/`），跑完后自动对比并打印 `新增 / 修改 / 删除 / 目录` 变更清单。默认选择丢弃，真实工作区文件分毫未损。

### 5. 编辑器接入（ACP）与命令行补全（FIM）

**作为编辑器 ACP 后端（如 Zed）**：

在编辑器的配置文件中添加 [bin/dojo](https://github.com/rar-zip/dojo/blob/main/bin/dojo) 的 `acp` 启动项：

```json
{
  "agent_servers": {
    "dojo": {
      "command": "dojo",
      "args": ["acp"]
    }
  }
}
```

`dojo acp` 运行在标准输入输出（stdio）JSON-RPC 2.0 协议之上，支持 `initialize`、`authenticate`、`session/new`、`session/prompt` 与 `session/cancel`，通过 `session/update` 实时流式推送回答，并在能力握手时严格声明 `fs: false` 与 `terminal: false`，确保编辑器端完全只读、绝不越权改写代码。

**命令行 FIM 补全（`dojo complete`）与 Ctrl-G 绑定**：

```bash
# 通过参数传入前缀与可选后缀
dojo complete -p "find /var/log -name '*.log' " -n 64

# 通过标准输入管道以 \0 分隔传入光标前后文（便于绑定至 Readline / ZLE 快捷键）
printf '%s\0%s' "tar -czf backup.tar.gz " " --exclude=.git" | dojo complete
```

装完 hook 之后，`Ctrl-G` 已经绑到行内补全：命令敲到一半按下去，光标前后文自动丢给 `dojo complete`，补出来的片段接到光标处。想换键位，改 `lib/hook.bash` 里的 `bind -x` 或 `lib/hook.zsh` 里的 `bindkey` 那一行即可。

## 配置文件参考

配置文件位于 `~/.config/dojo/config.toml`（文件权限强制为 `0600`），支持任意兼容 OpenAI Chat Completions 接口的模型服务：

```toml
[model]
base_url = "https://api.deepseek.com/v1"  # 支持 DeepSeek 或任意 OpenAI 兼容网关
model = "deepseek-flash"                  # 推荐 deepseek-flash 或 deepseek-chat
api_key = ""                              # 留空时自动读取环境变量 DEEPSEEK_API_KEY / DOJO_API_KEY / OPENAI_API_KEY
stream = true
timeout_seconds = 90

[assist]
level = 3                                 # 默认协助等级 (1-5)

[context]
history = 8                               # 携带最近 N 条终端命令作为上下文
capture_stderr = true                     # 通过 PTY 代理捕获终端 stderr（保留颜色与 isatty）
auto_explain = true                       # 空敲 dojo 且上一条命令失败时是否直接诊断报错

[exec]
max_snapshot_mb = 200                     # 单步快照最大体积上限 (MB)
max_step_seconds = 600                    # 单步执行超时时间 (秒)，超时自动中断并回滚
ttl_days = 7                              # 历史运行快照保留天数
capture_output = true                     # L5 代跑时通过 PTY 捕获输出至 runs/<id>/output.log
output_max_kb = 512                       # 单次运行输出日志轮转上限 (KB)
offer_sudo = true                         # 识别缺 root 权限时是否主动询问提权

[safety]
redact_secrets = true                     # 落盘与请求模型前自动脱敏 API Key / Token / 密码
deny_paths = ["/etc", "/boot", "/usr", "/var/lib", "/sys", "/proc"]
require_typed_confirm = false             # 高风险操作是否要求手动输入“确认”二字

[stop]
ask = true                                # 按下 Ctrl+C 时是否弹出 4 选 1 刹车菜单（false 则直接中断并回滚）
timeout_seconds = 15                      # 刹车菜单无操作自动回滚倒计时 (秒)

[persona]
name = "老王"                             # 陪练角色名称
```

## 项目结构与开发测试

```text
dojo/
├── bin/
│   └── dojo                  # 核心可执行程序（单文件零依赖 Python 实现）
├── lib/
│   ├── hook.bash             # Bash 命令记录与 PTY stderr 无损转发，含 Ctrl-G 补全
│   └── hook.zsh              # Zsh 命令记录与 PTY stderr 无损转发，含 Ctrl-G 补全
├── tools/
│   └── build_installer.py    # 将 bin/dojo 与 lib/hook.* 编码合成为单文件安装器
├── dist/
│   └── dojo-install.sh       # 构建生成的自包含一行安装脚本
├── tests/
│   └── test_core.py          # 单元与端到端回归测试（解析 / 快照 / PTY / 沙盒 / ACP / FIM / hook）
├── docs/
│   ├── 技术方案.md            # 架构设计规范与停止/回滚状态机说明
│   └── 路线图-v0.7-v1.0.md    # 后面几版怎么走
├── install.sh                # 源码本地安装脚本
└── Makefile                  # 常用构建与测试入口
```

在本地运行回归测试与打包构建：

```bash
# 运行完整回归测试套件（严格模式，零告警容忍）
python3 -W error tests/test_core.py

# 重新构建 dist/dojo-install.sh 单文件安装器
python3 tools/build_installer.py
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

## 开源许可

本项目基于 [MIT License](https://github.com/rar-zip/dojo/blob/main/LICENSE) 开源。
