# S1 · 心愿单盯价 Wishlist Watcher

## 一句话

你说一句“想买但再等等”，它把这句话变成一条长期监控；在真的降价、出券、接近历史低价时，带着理由回来找你。

## 当前阶段

**v0.4（D1–D3 + 零配置安装）已实现**：标准 Agent Skill 包、`npx skills` 安装、内置 beta 通道一键安装、首次运行 `setup` 状态机、商品建档、真实海纳查价、目标价/自入库最低价触发、24 小时冷却、再等等/买了/不准反馈。

另外包含一个 **3–5 人内测代理**（`proxy/`）：海纳 Key 只放 Cloudflare Worker secret；
客户端内置一个公共 beta token（`beta-proxy.json`，非密钥，可轮换），朋友装完即用。

尚未实现（D4–D5）：好价条件富化、多平台同款匹配、图搜/截图录入、跨 agent 实测矩阵、发布打包。

可行性调研见 [feasibility.md](./feasibility.md)。

## 安装

> ⚠️ 仓库目前是**私有**的。`raw.githubusercontent.com` 和 `npx skills add` 都需要有权限的 GitHub 身份，
> 匿名的一行命令不可用。分发方式见下面「私有仓库怎么发给朋友」。

已经 clone 仓库时：

```bash
bash install.sh --repo .
```

不用发 token，也不用配任何东西——Skill 自带 beta 通道。

脚本会：

1. 检查 Python 3.10+
2. 用 `npx skills` 把 Skill 装到已检测到的 agent（Claude Code / Codex / OpenCode / Cursor 等）
3. 运行 `setup`，确认已就绪

装完打开 agent，直接说：

```text
帮我盯 索尼 A7C2，降到 8000 告诉我
```

**凭证是怎么来的**：仓库里**没有任何 token**。`beta-proxy.json` 只有代理地址；
客户端第一次查价时向 `POST /v1/session` 申请一张 30 天有效的签名通行证，
存到 `~/.wishlist-watcher/session.json`（0600），过期或 401 时自动续。
服务端凭 `SESSION_SECRET` 验签，不存数据库；需要时轮换该 secret 即可让所有通行证立即失效。
海纳 Key 和上游地址始终只在 Worker secret 里。

想用单独发的、可单独撤销的 token：

```bash
bash install.sh --repo . --token invite-xxxx
```

### 私有仓库怎么发给朋友

三条路，按省事程度：

1. **加协作者**：把对方 GitHub 账号加为 read 权限，对方先 `gh auth login`，再
   `npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y`。
   代价是对方能看到整个仓库。
2. **发打包**：维护者把 `skills/wishlist-watcher/` 压成 zip 发给对方，解压到
   `~/.agents/skills/wishlist-watcher/`（或对应宿主的 skills 目录）。
   对方看不到仓库，但在本地能看到全部 skill 代码和 beta token。
3. **发版到公开安装点**：保留私有源码，另建一个只含 skill 包的公开仓库或由 Worker
   提供 `/install.sh` + 打好的包。工作量最大，但源码不外泄，且能集中控制 token。

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

已经 clone 仓库时：

```bash
bash install.sh --repo .
```

安装细节与各宿主路径见 [docs/INSTALL.md](./docs/INSTALL.md)。

## 它是什么

一个 **Agent Skill**，不是独立 App：

- `skills/wishlist-watcher/SKILL.md`：告诉任何 Agent 怎么触发、怎么问、怎么展示、怎么回收反馈。
- `skills/wishlist-watcher/scripts/`：确定性执行层，负责海纳取价、状态、规则，不让模型心算价格。
- 本地 JSON 状态：换会话/换 Agent 只要指向同一目录就能继续。

只依赖 **Python 3.10+ 标准库**，不需要 MCP、浏览器、特定模型或特定 Agent API。

## 快速开始

### 1. 安装 Skill

推荐：

```bash
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y
```

只装到特定 agent：

```bash
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y -a claude-code -a opencode
```

手动安装：把 `skills/wishlist-watcher/` 整个目录复制到宿主的 skills 目录，例如 `~/.claude/skills/wishlist-watcher/`。

### 2. 选择数据源模式

**模式 A：邀请代理（推荐给朋友，不需要海纳 Key）**

正常情况下不需要这一步：Skill 自带 beta 通道，`setup` 直接返回 `ready=true`。
只有想换成自己的 token 或自建代理时才需要：

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py login --token "邀请 token"
```

内置代理地址，正常不需要 `--url`；自建代理才需要。

**模式 B：直连海纳（自己的 Key）**

```bash
export HAINA_API_KEY="你的海纳 Key"
```

或写入 `~/.wishlist-watcher/.env.local`：

```text
HAINA_API_KEY=...
```

代理模式优先于直连；`setup` / `doctor` 会显示当前是 `proxy` 还是 `direct`。

### 3. 首次运行状态机

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py setup --format json
```

- `ready=true`：可以建档查价。
- `ready=false`：按 `next_action.command` 操作。正常安装不会出现这个状态；
  只有手动清掉配置、又没设 `HAINA_API_KEY` 时才会要求登录。

环境自检：

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py doctor --network
```

### 4. 首次使用说明

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py welcome --mark
```

Agent 应把输出原样发给用户；只自动发一次。

### 5. 建档

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000
```

如果有多个候选，会输出候选列表；确认后：

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2
```

### 6. 查价

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py check
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py check --id w_xxxx
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py list
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py show w_xxxx
```

### 7. 反馈

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py feedback w_xxxx --action wait --days 7
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py feedback w_xxxx --action bought
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py feedback w_xxxx --action inaccurate --note "点进去价格不对"
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py feedback w_xxxx --action resume
```

### 8. 删除代理配置

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py logout
```

只会删除本地 `~/.wishlist-watcher/proxy.json`；环境变量请自行取消。

### 离线演示

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py demo
```

## 提醒示例

```text
【值得买】索尼（SONY）A7C2 全画幅微单相机
当前到手 ¥8,531.45（页面价 ¥10,129.00）
京东 · 索尼（SONY）影像京东自营专区
历史最低 ¥8,609.65（页面价口径） / 30天最低 ¥8,609.65 / 常卖价 ¥10,783.00
触发：达到目标价
比目标价低 ¥468.55
检查时间：2026-10-21T13:42:56+08:00
条件：以结算页为准；如有地区/会员/券限制，请点开确认
[查看商品](...)
```

## 数据口径

- `price` / `price_cents`：**到手价**，用于目标价判断。
- `page_price`：**页面价**，仅展示。
- 海纳 `price_tags` 的“历史最低/30天最低/常卖价”是**页面价口径**，只展示，不和到手价直接比较。
- 自建 `lowest_seen_cents` 才是本 Skill 观察到的到手价最低值。

## 目录

```text
.
├── skills/wishlist-watcher/   # 可被 npx skills 安装的 Skill 包
│   ├── SKILL.md               # Agent 入口与对话协议
│   ├── agents/openai.yaml     # OpenAI/Codex 形态的元数据（可选）
│   ├── references/
│   │   ├── haina-api.md       # 海纳接口、字段、价格口径
│   │   ├── alert-rules.md     # 触发/冷却/降噪规则
│   │   └── host-compat.md     # 跨 agent 兼容与降级说明
│   ├── scripts/
│   │   ├── haina.py           # 海纳客户端
│   │   ├── store.py           # 本地状态
│   │   ├── rules.py           # 触发规则
│   │   └── watch.py           # CLI
│   └── fixtures/              # 离线演示数据
├── install.sh                 # macOS/Linux 一条命令安装
├── install.ps1                # Windows 一条命令安装
├── README.md
├── SECURITY.md                # 密钥/代理安全说明
├── LICENSE                    # MIT
├── .github/workflows/test.yml
├── data/schema.md             # 状态 schema
├── docs/
│   ├── INSTALL.md             # 各宿主安装与排错
│   └── VERIFICATION.md        # D1–D3 验证记录
├── proxy/                     # 3–5 人内测代理（Cloudflare Worker）
│   ├── src/index.ts
│   ├── wrangler.toml
│   └── README.md
├── tests/                     # 单元/CLI/代理配置测试
└── feasibility.md
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

代理类型检查：

```bash
cd proxy
npm install
npm run typecheck
npx wrangler deploy --dry-run
```

## 边界

- 只做提醒，不自动下单、不抢券、不模拟登录。
- 不做全网商品发现/推荐。
- 价格以结算页为准；地区/会员/券条件需用户确认。
- v0 输入是商品名/型号，不是商品链接或截图。
- 主动提醒依赖宿主定时任务；没有定时能力时只能手动 `check`。
- 内测代理不包含用户配额，只有全局日上限/QPS 保险丝；公开运营前需确认海纳授权。

## 下一步（D4–D5）

1. 接入好价检索 Pro，展示券/活动/购买步骤和“为什么值得买”。
2. 多平台同款匹配：套机/单机身/颜色/规格分开。
3. 图搜商品/截图录入。
4. 跨 agent 实测：OpenCode、Claude Code、Codex；记录路径、shell、状态恢复差异。
5. 误报回收：结算页截图与价格校正。
