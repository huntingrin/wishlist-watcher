---
name: wishlist-watcher
description: 心愿单盯价。用户说“帮我盯某商品，降到某价告诉我”或询问已盯商品时使用；通过海纳取价、本地建档、到价提醒，不自动下单。适用于任何能执行 Python 3.10+ 的 Agent。
---

# 心愿单盯价

把“想买但再等等”变成一条本地监控：确认商品、记录目标价、定期查价、只在触发时提醒。

## 首次使用：先 setup

Skill 首次被调用时，**必须先运行**：

```bash
python3 <skill-dir>/scripts/watch.py setup --format json
```

按返回处理，不要跳过：

- `ready=true`：继续下面的欢迎语流程，可以正常建档查价。
- `ready=false`：只执行 `next_action.command`，把 `next_action.message` 告诉用户；**不要**假装已经能查价。
  - `reason=needs_data_source`：说明这个版本没有可用通道，让用户找维护者；有海纳 Key 的用户可改用 `export HAINA_API_KEY=...`。
  - `reason=proxy_config_invalid`：先 `logout`，再重新 `login`。
  - `reason=python_too_old` / `state_dir_unwritable`：按 `next_action` 修复。
- 修复后重新运行 `setup`，直到 `ready=true`。

`setup` 返回 0 只代表检查执行成功，不代表已就绪；以 `ready` 字段为准。

就绪后运行：

```bash
python3 <skill-dir>/scripts/watch.py welcome --format json
```

如果返回 `first_run=true`，把 `message` **原样**发给用户，然后再运行一次 `welcome --mark --format json`，避免下次重复。如果 `first_run=false`，不要主动重复发；用户问“怎么用 / 帮助”时可以再发。

如果宿主支持 skill 加载钩子，可在钩子里调用 `welcome --mark`；否则在首次被调用时发送。不要承诺“安装瞬间弹消息”，这取决于宿主能力。

## 数据源模式

两种模式二选一，代理优先：

**直连海纳**：用户自己的 `HAINA_API_KEY`，适合本地/开发者。

**内置 beta 通道**（默认）：Skill 自带 `beta-proxy.json`，装完 `setup` 就是 `ready=true`，
用户不需要 token、不需要任何配置。里面的 token 是公开的 beta 凭证，不是密钥。

**可选：单独发的邀请 token**（可单独撤销，优先于 beta 通道）：

```bash
python3 <skill-dir>/scripts/watch.py login --token "<邀请 token>"
```

- 内置代理地址，正常只需 token；自建代理才加 `--url`。
- token 保存到 `~/.wishlist-watcher/proxy.json`（0600），不要回显、不要写进对话。
- 优先级：环境变量 > `proxy.json` > 自己的 `HAINA_API_KEY` > 内置 beta。
- `doctor` 会显示 `mode: proxy` 或 `mode: direct`。
- 删除配置：`python3 <skill-dir>/scripts/watch.py logout`。
- 公开仓库包含代理代码和公开 beta token；海纳 Key 与上游地址永远只在 Worker secret 里。

## 用户怎么说

| 用户表达 | 动作 |
|---|---|
| “帮我盯 X，降到 Y 告诉我” | `add`，需要时让用户选候选 |
| “这个现在多少钱 / 值得买吗” | 先 `add` 查候选，或对已有项 `show` |
| “我盯的东西怎么样了” | `list`，需要时 `check` |
| “查一下” | `check` |
| “买了 / 再等等 / 不准” | `feedback` |
| “怎么用” | `welcome` |

## 建档

```bash
python3 <skill-dir>/scripts/watch.py add "<商品名/型号>" --target <目标价> --format json
```

- 如果返回 `status=needs_pick`，把 `candidates` 里的 3–5 个候选展示给用户，让用户确认序号；然后：

```bash
python3 <skill-dir>/scripts/watch.py add "<商品名/型号>" --target <目标价> --pick <N> --format json
```

- 只让用户确认**一次**。确认后把返回的 `item.product.title` 当作稳定商品名，后续用 `product.search_query` 重新检索并匹配。
- 目标价是**到手价**，不是页面价。用户说的“降到 8000”默认按到手价理解；如果用户明确说页面价，先说明口径差异。
- 不要替用户猜商品。套机、单机身、不同颜色/规格必须让用户选。

## 查价与提醒

```bash
python3 <skill-dir>/scripts/watch.py check --format json
# 或只查一个：
python3 <skill-dir>/scripts/watch.py check --id <id> --format json
```

- `check` 会调用海纳商品检索 Pro，按建档时的搜索词重新召回，并匹配用户确认过的商品。
- 只有 `alerts` 非空时才主动提醒。`alerts[].card` 是可以直接发给用户的 Markdown 卡片。
- 没有触发时，给一句简短状态即可，不要每天推促销流。
- 触发规则见 `references/alert-rules.md`：目标价、跌破自入库最低价、24 小时冷却、再等等。

## 反馈

```bash
python3 <skill-dir>/scripts/watch.py feedback <id> --action wait --days 7
python3 <skill-dir>/scripts/watch.py feedback <id> --action bought
python3 <skill-dir>/scripts/watch.py feedback <id> --action inaccurate --note "点进去价格不对"
python3 <skill-dir>/scripts/watch.py feedback <id> --action resume
```

- `wait`：进入 7 天冷却，不改变 active 状态。
- `bought`：归档，不再检查。
- `inaccurate`：标记待核对，暂停 1 天；提醒用户下次带结算页截图/条件。
- `resume`：恢复 active 并清空冷却。

## 输出规范

默认 `--format markdown`，直接展示。需要程序解析时用 `--format json`。

价格字段统一为整数分：

- `price_cents`：到手价，用于目标价判断。
- `page_price_cents`：页面价，仅展示。
- `historical_low_cents` / `low_30d_cents`：来自海纳 `price_tags`，是**页面价口径**，只展示，不能和 `price_cents` 直接比较。
- 自建 `lowest_seen_cents`：本 Skill 观察到的到手价最低值，用于“跌破自入库最低价”。

提醒必须带：

1. 商品名、平台/店铺
2. 当前到手价、页面价
3. 触发原因
4. 历史/30 天/常卖价参考（标注口径）
5. 检查时间
6. “以结算页为准；地区/会员/券条件需点开确认”
7. 商品链接

## 边界

- 只做提醒，不自动下单、不抢券、不模拟登录、不抓取页面。
- 不把海纳返回的价格当成用户最终结算价；提醒里必须保留“以结算页为准”。
- 不把 API Key 写进对话、状态文件或日志。
- 没有拿到可靠价格、没有匹配到已确认商品时，不提醒。
- 海纳是第三方数据源，可能延迟/缺货/条件变化；错误如实说明，不编造价格。

## 宿主兼容

详细矩阵见 `references/host-compat.md`。

- 只依赖 **Python 3.10+ 标准库**；不需要 MCP、浏览器、特定模型或特定 Agent API。
- 状态默认在 `~/.wishlist-watcher/watchlist.json`；可用 `--state-dir` 覆盖。换会话/换 Agent 只要指向同一目录即可恢复。
- API Key 从 `HAINA_API_KEY` 环境变量读取；也支持 `~/.wishlist-watcher/.env.local`。不要把 Key 放进 Skill 目录或仓库。
- 内测代理模式用 `login` 保存 `~/.wishlist-watcher/proxy.json`；token 等同于密码，不要回显到对话或日志。
- 定时检查：由宿主调用 `check`（cron/launchd/Task Scheduler/宿主定时任务均可）。Skill 本身不常驻、不保证主动推送。
- 宿主不能执行 shell：只能使用 `references/haina-api.md` 做单次查询说明，不能提供持久化监控；不要假装已经建档。
- 路径含空格/中文、Windows 路径均由 Python `pathlib` 处理；不要要求用户安装 `jq`、`curl` 或额外 Python 包。
