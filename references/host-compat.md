# 宿主兼容说明

本 Skill 的目标是：同一份 `SKILL.md` + `scripts/` 能在不同 Agent 里工作，而不是绑定某一个宿主。

## 依赖

- Python 3.10+
- 标准库（`urllib`、`json`、`pathlib`、`datetime`）
- 可执行 shell 命令的宿主（用于运行 `watch.py`）
- 海纳 API Key

不依赖：

- MCP Server
- 浏览器 / 登录态
- 特定模型或特定 Agent API
- `jq`、`curl`、`node`、第三方 Python 包

## 命令名

不同系统/宿主可能只有 `python` 或 `py`：

```bash
python3 scripts/watch.py doctor
python  scripts/watch.py doctor
py -3   scripts/watch.py doctor
```

`SKILL.md` 默认写 `python3`；宿主可按自己的解释器替换。

## 状态与密钥

- 状态：`~/.wishlist-watcher/watchlist.json`
- 覆盖：`--state-dir <绝对路径>`
- 直连 Key：`HAINA_API_KEY` 环境变量，或 `~/.wishlist-watcher/.env.local`
- 内测代理：`watch.py login --url ... --token ...`，保存到 `~/.wishlist-watcher/proxy.json`
- 换 Agent/换会话只需指向同一 `--state-dir`。

## 能力分级

| 宿主能力 | 能做什么 | 不能做什么 |
|---|---|---|
| shell + Python + 网络（直连或代理） | 完整建档、查价、提醒、反馈 | 自动下单（本来就不做） |
| HTTP 工具 + 网络，无 shell | 按 `references/haina-api.md` 做单次查价 | 持久化监控、定时检查 |
| 无网络/无 shell | 解释用法、展示离线 demo | 真实查价、建档 |

内测代理模式能力相同，只是请求指向代理；用户拿的是邀请 token，不是海纳 Key。

不要在没有执行能力时假装已经建档或已经查价。

## 定时检查

Skill 不内置常驻进程。宿主可用自己的调度能力调用：

```bash
python3 /absolute/path/to/scripts/watch.py check --format json
```

- macOS/Linux：cron / launchd
- Windows：Task Scheduler
- Agent 平台：宿主定时任务/工作流
- 没有定时能力：用户手动说“查一下”

主动提醒依赖宿主的推送能力；没有推送时，`check` 的结果只能显示在当前对话里。

## 跨 Agent 自检清单

1. 从不同工作目录运行 `watch.py demo`。
2. 用带空格/中文的 `--state-dir` 运行 `welcome --mark`。
3. 第二个 Agent 会话读取同一个 `--state-dir`，执行 `list`。
4. `doctor --format json` 能被宿主解析。
5. 检查日志/状态/仓库中没有完整 API Key。
6. 宿主不支持 shell 时，确认 `SKILL.md` 的降级说明生效，不编造结果。
