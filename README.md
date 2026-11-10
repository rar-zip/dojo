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

## 用

```bash
dojo                        # 当前状态
dojo ask "这报错啥意思"      # 问一句
dojo explain                # 解释上一条命令（带退出码和 stderr）
dojo do "把日志里 500 的行数出来"   # 让它给方案，L5 下逐步确认执行
dojo run "df -h"            # 直接跑一条（L5，仍要确认）
dojo undo                   # 撤掉最近一步
dojo undo all               # 撤掉最近一次运行的全部步骤
dojo history                # 看运行记录
dojo stop                   # 让正在跑的任务停手
dojo level 3                # 切协助等级
dojo log                    # 看它眼里的上下文
dojo doctor                 # 自检
```

## 协助等级

| 级 | 行为 |
|---|---|
| L1 | 旁观：只答不问，一句话 |
| L2 | 讲解：讲原理，不给命令 |
| L3 | 指路：给方向、关键词、man 页（默认） |
| L4 | 代笔：给完整命令，你自己敲 |
| L5 | 陪练：可以申请代跑，每条都要你点头 |

L5 下 `dojo do "想做的事"` 的流程：

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

`dojo undo` 默认撤最近一步，`dojo undo all` 撤最近一次运行的全部步骤。

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
capture_stderr = false

[exec]
max_snapshot_mb = 200

[stop]
ask = true
timeout_seconds = 15
```

### capture_stderr

默认关。打开后 shell 启动时把 stderr 复制一份到 `~/.local/state/dojo/stderr.log`，
`dojo explain` 才能看到真正的报错文本。

代价：stderr 不再是 tty，少数程序（尤其带颜色的）输出行为会变。新手先别开。

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

## 开发

```bash
python3 tests/test_core.py     # 14 个用例：解析 / 快照 / 回滚 / CLI
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
```

## 路线

- [x] P1 只看只说，流式回答
- [x] P2 L5 代跑，一步一确认，Ctrl+C 刹车
- [x] P3 快照 / undo / 系统级操作分级
- [ ] 更聪明的快照（按命令影响面推断，而不是关键词）
- [ ] 会话内记忆与多轮任务
- [ ] 更多模型后端

## License

MIT
