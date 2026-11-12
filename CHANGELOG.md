# 更新记录

## 0.8.5

- **镜像顺序调整**：jsDelivr 会缓存 `@main`，刚发版时仍吐旧包（purge 也不一定立刻生效）。顺序改成 raw → gh-proxy → ghfast → jsDelivr，把可能过期的源放最后
- README 的手动换源示例也换成 gh-proxy / ghfast
- `dojo upgrade --file` 的离线说明同步更新

## 0.8.4

- **下载优先走 IPv4**：`urlopen error [Errno 101] Network is unreachable` 多半是只解析到 AAAA 记录、机器却没有 v6 出口。现在解析时先拿 A 记录，拿不到再退回原来的行为
- **网络错误翻成人话**：101/99 说没路由，110/60 说超时，111 提示本地代理可能挂了，DNS 失败提示看 resolver
- **新增 `dojo upgrade --file <脚本>`**：没外网的机器可以先在别处下好 61 KB 的安装器，拷过去直接装或升级
- README 补了离线安装一节
- 测试 83 → 85

## 0.8.3

- **安装器体积 196 KB → 61 KB**：payload 先 gzip 再 base64，装的时候 `base64 -d | gunzip`。小样本机上 `wget | bash` 快很多，断流概率也低
- **每个源重试 2 次**：`dojo upgrade` 每个镜像最多试两次，中间歇 1.5 秒，弱网下不至于一次抖动就判死
- 校验：用假 HOME 跑了一遍安装器，装出来的 `dojo` 和仓库里的字节一致
- 测试仍是 83 项

## 0.8.2

- **`dojo upgrade` 多镜像自动退让**：raw.githubusercontent 国内经常连不上，现在按 GitHub raw → jsDelivr → gh-proxy → ghfast 依次重试，哪个通用哪个，并把用的源打出来
- **全部不通时给具体原因和人话建议**：每个源失败原因都列出来，提示换网 / 开代理 / `git pull` 重装，或者用 `DOJO_INSTALL_URL=<地址> dojo upgrade` 钉死某个源
- README 补了手动换源的写法
- 测试 80 → 83（多源退让、全挂、显式指定各一条）

## 0.8.1

v0.8.0 收口没做完的两处，补上。

- **`dojo --foo` 不再当人话发给模型**：以 `-` 开头的未知选项直接报「没有这个选项」并打帮助，退出码 1。以前会被当成提问，白花一次 token
- **帮助菜单按三组重排**：说话 / 控制 / 查账与管理，41 行压到 25 行。老命令（`ask`、`run`、`errors`、`history`、`commands`）全部保留，只是不再占帮助版面
- README 的命令速查也按同样三组重写
- 测试 80 项，`-W error` 零警告

## 0.8.0

入口收口。子命令涨到 21 个之后，「说句话」这一层成了负担：想问句什么都得先选 `ask` / `why` / `run` / `explain`。

- **说话免指令**：`dojo 80端口被谁占了` 直接用。没匹配到子命令时整串当成对话，按当前状态选路：最近有报错且 L1–L4 → `why`（带报错现场）；L5 → `do`（出方案并逐条确认）；其余 → `ask`
- **子命令写错给提示**：`dojo stauts` 不再甩一屏帮助，改成一句「你是不是想 dojo status」，然后退出
- **历史入口收拢**：`dojo log` / `log err` / `log run` 覆盖原来 `log` / `errors` / `history` / `commands`，老命令全部保留做别名
- **控制类指令不吃自然语言**：`undo` / `stop` / `exec` / `preview` 必须是明确子命令，救命和撤销要确定性，字面命令要原样跑
- 测试 76 → 80

## 0.7.0

交互手感这一层收口，把已经通了的能力真正接到手边。

- **`dojo 1` / `dojo 2` / `dojo 3` 直接跑方案**：报错卡片里的三条方案现在会存成 `last_card.json`，敲个数字就能跑第 N 条，走 `Runner`，跑前照样有快照，`dojo undo` 照常能撤
- **`dojo diff [运行ID]`**：撤之前先看清楚改了哪几行。拿 `runs/<id>/steps/` 的备份跟当前工作区做 unified diff，目录快照会逐个文件比，二进制跳过
- **Ctrl-G 行内补全**：`lib/hook.bash` 用 `bind -x` + `READLINE_LINE`，`lib/hook.zsh` 用 `zle` + `LBUFFER`，敲命令敲到一半按 Ctrl-G，把光标前后文丢给 `dojo complete`，补出来的直接塞回光标处。想换键位改 hook 里那行 `bind` / `bindkey` 就行
- 修一处帮助文本少换行，`dojo why` 和 `dojo acp` 两行以前粘在一起
- 测试 69 → 76

## 0.6.2

- **hook 转发不再吐 `\r\r\n`**：内层 PTY 关掉 `OPOST` 之后，程序自己写的 `\r\n` 会被外层终端再转一次。转发时把连续的 `\r` 压成一个，`\r` 和 `\n` 被拆进两次 read 的情况也处理了（攒住结尾的 `\r` 等下一块）
- 测试 68 → 69，给这条补了一个 PTY 回归；顺手关掉了测试里没释放的 socket、子进程和管道（`-W error` 下不再有 ResourceWarning）

## 0.6.1

六个真问题，全部有复现路径：

- **修 hook 吞掉整个终端**（致命）：hook 里先 `setsid()` 再去 `open("/dev/tty")`，脱离控制终端后必然 ENXIO，转发进程拿不到 tty，只把数据写进 `stderr.log`。结果是开了 `capture_stderr` 之后提示符、打字回显、所有报错在屏幕上一个都看不到。改成 fork 前先抓住终端（拿不到就 `dup(2)` 兜底），并关掉内层 PTY 的 `OPOST`，避免 `\n` 被转义两次变成 `\r\r\n`
- **提权后命令判错可逆**（高危）：`_sudo_wrap()` 把命令包成 `sudo -- bash -c '...'`，`classify()` 只看到 `bash`，`apt install` 这类被判成可逆，`dojo undo` 也给不出反向命令。新增 `_shell_c_payload()`，`_cmd_args()` 现在穿透 `sudo [--] bash/sh/zsh -c`
- **代跑命令日志污染真实目录且未脱敏**（高危）：`COMMANDS_LOG` 没进 `_refresh_paths()` 的 global 列表，`DOJO_STATE_DIR` 换了它不跟着换，测试里的假命令会写进真实 `~/.local/state/dojo/commands.log`；`log_command()` 也直接落原始命令。现在跟着刷新，并按 `safety.redact_secrets` 脱敏
- **`dojo preview` 退出码恒为 0**（中危）：`main()` 没接 `cmd_preview()` 的返回值，被 L3 拦下（1）或被策略拦下（2）都返回 0，脚本里没法判断
- **沙盒合并 `rm f && mkdir f` 崩溃**（中危）：`_apply_upper()` 对目录直接 `makedirs(exist_ok=True)`，真实路径上还是同名普通文件时抛 `FileExistsError`；现在先让路
- **ACP/FIM 三处细节**：`_fim_url()` 只在 deepseek.com 下才拼 `/beta/completions`，其他兼容端点用 `/completions`；`cmd_complete` 的 prefix/suffix 走 `redact_sensitive`；`cmd_acp` 对坏 JSON 回 `-32700`，对带 id 的 `session/cancel` 补回 `{}`
- 配置一致性：`install.sh` 的 `capture_stderr` 改成 `true`，跟 CHANGELOG 和内置默认值对齐；hook 改为「只要没显式写 false 就开」，并支持 `DOJO_CONFIG`
- 测试 61 → 68，`python3 -W error tests/test_core.py` 零警告

## 0.6.0

- **空敲 `dojo` 直接答报错**：上一条命令失败（退出码非 0、一小时内）时，不再打印状态，直接让老王说为什么挂、先看哪里、怎么修
- **报错回答固定格式**：原因 / 猜测 / 方案 三段，模型只允许回 JSON，渲染由 dojo 负责；方案里的每一条都是能直接执行的命令，不是文字分析，也不再标「老王」
- **新增 `dojo why "我其实想……"`**：三条方案都不对时，用一句话说清目的，它带着刚才的报错重新给准确做法
- **新增 `dojo errors [N]`**：列出最近失败的命令，带时间和退出码
- **`capture_stderr` 默认改成开**：新装默认能拿到报错正文；老配置里写死了 false 的不受影响，要手动开
- **新增 `dojo acp`**：stdio 上的 ACP agent（JSON-RPC 2.0），实现 initialize / session/new / session/prompt / session/cancel，流式回 `session/update`；不碰文件系统和终端，只负责说
- **新增 `dojo complete`**：DeepSeek FIM（`/beta/completions`）补全，只输出补出来的那段，无换行，方便 shell/编辑器接
- 抽出 `iter_model_stream()`，ACP 与终端流式共用同一套解析
- 测试 57 → 61

## 0.5.4

- **缺 root 权限时会申请提权**：
  - 方案里有 `apt` / `systemctl` / `useradd` 这类命令却没加 sudo，跑之前先问「要我加上 sudo 吗」
  - 跑挂了且输出里有 `Permission denied` / `are you root` 这类，再问「要我加 sudo 重跑这一步吗」
  - 提权按系统级操作处理，明说撤不回来；`exec.offer_sudo = false` 可以关掉
- 复合命令用 `sudo -- bash -c` 整条包起来，不会只提权前半段
- 测试 49 → 51

## 0.5.3

真正的原因找到了：deepseek-flash 是推理模型，900 tokens 的预算大半烧在思考上，`finish_reason=length`，正文只吐了半截就断，所以「方案只做了一半」不只是提示词的问题。

- `call_model` 检测到 `finish_reason == "length"` 或正文为空时，自动把预算翻倍重试（最多 4096，静默，不打扰）
- `dojo run` 初始预算 900 → 1600
- `PLAN_HINT` 追加：不同发行版命令不一样的，用 `if/elif` 写成一段，别给两套并排方案
- 实测「装个更好的中文输入法」现在一次给出：侦察 → 按包管理器分支安装 → 环境变量 → 拉起 fcitx5 → 验证，五步齐

## 0.5.2

- **方案必须一次给全**：`PLAN_HINT` 改成「从查现状、到安装或修改、到验证结果，一条不漏；只给一条侦察命令等于没给方案」
- **侦察命令会被打回**：整份方案全是 `cat` / `uname` / `ls` 这类只读命令时，自动再问模型一次，让它把剩下的步骤补上（最多补一次，补不出来会明说方案不完整）
- 新增 `plan_is_recon_only()` 判定，带单测

## 0.5.1

- **`dojo run` 不再跑一步就收摊**：上一轮执行过什么会带回给模型，按回车就接着下一步，直到模型说 DONE；不再是「侦察一条 cat /etc/os-release 就结束」
  - 追问提示改成「回车继续下一步 / 直接打字改需求 / q 结束」，默认行为从结束变成继续
  - 最多 8 轮，防死循环
- `PLAN_HINT` 改成「侦察之后别停，把后面要做的也按顺序写出来」，减少挤牙膏
- `dojo init` 发现 `.bashrc` 里的 hook 路径失效（仓库搬家、老安装器写死路径）会直接重写，不再误报「已经在里面了」

## 0.5.0

Gemini 那份 roadmap 里剩下的两条，加上一个一直在拖的坑。

- **新增 `dojo preview`**：用 unshare + overlayfs 把当前目录套一层隔离层，命令在里面跑，跑完列出 新增/修改/删除，再决定应用还是丢弃。猜不到会碰什么的脚本、`git clean`、`make clean` 终于有安全预演了
  - `--apply` / `--discard` 跳过询问；没有交互终端时默认丢弃
  - 内核不支持用户命名空间时给明确提示，回落到 `dojo exec` + 快照
- **代跑输出进 PTY**：`dojo run` / `dojo exec` 的子进程改走 PTY，颜色和 `isatty` 保住，同时把输出写进该次运行的 `output.log`（512KB 轮转），`dojo log` 会带出最近一次输出的尾部
- **修 capture_stderr 破坏 isatty(2)**：shell hook 不再用 `exec 2> >(tee ...)`，改成 python 开一对 PTY 转发，彩色工具不再退化，日志照留
- 刹车时用后台线程继续泵 PTY，子进程不会因为输出写满而僵住
- 测试从 43 项加到 47 项：PTY 捕获、沙盒丢弃、沙盒应用、hook isatty

## 0.4.1

- 修 bash hook 在 `HISTCONTROL=ignoreboth` 下漏记连续相同命令的问题，改用 DEBUG trap 判断「真的执行了」
- 修 zsh hook 用命令内容去重导致同样命令第二条被吞，改用历史编号
- `stderr.log` 超过 512KB 自动截断，不再无限长
- 加 GitHub Actions：每次 push 跑测试，并检查 dist 安装器是否跟源码同步
- `docs/技术方案.md` 状态改成已实现，去掉「未开工」和 daemon 的错误描述


## 0.4.0

这一版把 Gemini 那份优化逐条过了，能用的合进来，也补上了自己的两条。

**修掉的坑**
- `rm -f`、`cp -f`、`mv -f` 里的 `-f` 不再被当成「带参数的选项」，目标文件能正确进快照（之前这类命令撤不回来）
- `sed -i.bak`、`sed -i -e` 的目标提取修好，连带清理 `.bak`
- 复合命令（`a && sudo systemctl ...`）整条识别不可逆，不再只看第一段
- 运行 ID 改成微秒加序号，同秒连跑不会互相覆盖、排序不会错
- 多步计划里 `cd` 的状态能带到下一步

**新东西**
- 安全策略：删根、格式化、fork 炸弹直接拒跑；`deny_paths` 保护系统目录；高危操作提示，可选手打确认
- 命令和对话里的密钥自动打码
- 单步超时，默认 600 秒，超时自动中断并回滚
- `dojo config get/set`、`dojo uninstall [--purge]`
- `dojo undo <运行ID>` 可以撤指定那次
- 快照带 SHA-256 校验，软链接和权限位能还原；过期快照按 `ttl_days` 自动清

**之前攒的两条**
- `dojo upgrade` 下载有进度条
- 每步打出「第 N/M 步 · 命令」和退出码，统一记到 `commands.log`，`dojo commands` 查看
- `dojo run` 说人话，`dojo exec` 跑字面命令，聊天里 `/run` 与 `/exec` 同理

测试 43 项全过。

## 0.3.2

- `dojo run "想做的事"` 改成说人话的入口，模型给方案再执行
- 跑字面命令改用 `dojo exec "命令"`
- 聊天里 `/run` 同理，字面命令用 `/exec`
- 30 项测试


## 0.3.1

- 新增 `dojo upgrade`：拉最新安装脚本并覆盖，旧版自动备份
- README 补了升级说明和源码升级路径
- 29 项测试


## 0.3.0

- 新增 `dojo chat`：常驻对话，追问不用重新起手，退出后下次还能接着上次的聊
- 聊天里直接用 `/run` `/undo` `/level` `/log` `/clear`，老王给命令时可以就地跑
- PERSONA 里禁了破折号，终端里看着清爽点
- 28 项测试，含 chat 的 pty 用例


## 0.2.0

- 快照更靠谱：会按管道、&&、分号拆开逐段分析，`cmd | tee f` 现在能撤
- `find ... -delete` 会先空跑一次找出命中项，再逐个快照
- xargs、命令替换、eval 这类猜不准的，跑之前就明说撤不了，不假装能撤
- 解压、git、rsync 这类按性质整目录快照
- `dojo do` 跑完可以接着说「还要改什么」，最多接五轮，不用重新起手
- 刹车默认回滚写进了自动化测试，26 项全过


## 0.1.1

- 修 `dojo stop`：没有任务在跑时不再留下过期停止标记，避免下一次运行一启动就停
- `dojo stop` 现在只对真正在跑的任务生效，会检查进程还在不在
- 新增 `dojo history`，看历次运行；`dojo undo <运行ID>` 可以撤指定那次
- 没配好时直接敲 `dojo` 会显示三步上手，不再甩一堆配置路径
- `dojo init` 顺手问 API key，输完写进配置文件（600）

## 0.1.0

- 第一个可用版本：默认只读，L5 一步一确认代跑，跑前快照，Ctrl+C 刹车，默认回滚
- 文件级 undo；系统级操作明确标注撤不了
- bash / zsh 命令记录，一行安装器
