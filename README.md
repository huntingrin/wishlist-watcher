# S1 · 心愿单盯价 Wishlist Watcher

## 一句话

你说一句“想买但再等等”，它把这句话变成一条长期监控；在真的降价、出券、接近历史低价时，带着理由回来找你。

## 当前阶段

**v0.3（D1–D3）已实现**：欢迎语、环境自检、商品建档、真实海纳查价、目标价/自入库最低价触发、24 小时冷却、再等等/买了/不准反馈。

另外包含一个 **3–5 人内测代理**（`proxy/`）：海纳 Key 只放 Cloudflare Worker secret，客户端只拿邀请 token。

尚未实现（D4–D5）：好价条件富化、多平台同款匹配、图搜/截图录入、跨 agent 实测矩阵、发布打包。

可行性调研见 [feasibility.md](./feasibility.md)。

## 它是什么

一个 **Agent Skill**，不是独立 App：

- `SKILL.md`：告诉任何 Agent 怎么触发、怎么问、怎么展示、怎么回收反馈。
- `scripts/`：确定性执行层，负责海纳取价、状态、规则，不让模型心算价格。
- 本地 JSON 状态：换会话/换 Agent 只要指向同一目录就能继续。

只依赖 **Python 3.10+ 标准库**，不需要 MCP、浏览器、特定模型或特定 Agent API。

## 快速开始

### 1. 选择数据源模式

**模式 A：直连海纳（自己的 Key）**

```bash
export HAINA_API_KEY="你的海纳 Key"
```

或写入 `~/.wishlist-watcher/.env.local`：

```text
HAINA_API_KEY=...
```

**模式 B：内测代理（不接触海纳 Key）**

```bash
python3 scripts/watch.py login \
  --url "https://wishlist-watcher-proxy.<subdomain>.workers.dev" \
  --token "你的邀请 token"
```

也可以不写 `--token`，改用环境变量：

```bash
export WISHLIST_PROXY_URL="https://..."
export WISHLIST_PROXY_TOKEN="..."
```

代理模式优先于直连；`doctor` 会显示当前是 `proxy` 还是 `direct`。

不要把 Key 或邀请 token 放进 Skill 目录、对话或仓库。

### 2. 环境自检

```bash
python3 scripts/watch.py doctor --network
```

### 3. 首次使用说明

```bash
python3 scripts/watch.py welcome --mark
```

Agent 应把输出原样发给用户；只自动发一次。

### 4. 建档

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 8000
```

如果有多个候选，会输出候选列表；确认后：

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2
```

### 5. 查价

```bash
python3 scripts/watch.py check
python3 scripts/watch.py check --id w_xxxx
python3 scripts/watch.py list
python3 scripts/watch.py show w_xxxx
```

### 6. 反馈

```bash
python3 scripts/watch.py feedback w_xxxx --action wait --days 7
python3 scripts/watch.py feedback w_xxxx --action bought
python3 scripts/watch.py feedback w_xxxx --action inaccurate --note "点进去价格不对"
python3 scripts/watch.py feedback w_xxxx --action resume
```

### 7. 删除代理配置

```bash
python3 scripts/watch.py logout
```

只会删除本地 `~/.wishlist-watcher/proxy.json`；环境变量请自行取消。

### 离线演示

```bash
python3 scripts/watch.py demo
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
├── SKILL.md                 # Agent 入口与对话协议
├── README.md
├── SECURITY.md              # 密钥/代理安全说明
├── LICENSE                  # MIT
├── .github/workflows/test.yml
├── agents/openai.yaml       # OpenAI/Codex 形态的元数据（可选）
├── references/
│   ├── haina-api.md         # 海纳接口、字段、价格口径
│   ├── alert-rules.md       # 触发/冷却/降噪规则
│   └── host-compat.md       # 跨 agent 兼容与降级说明
├── scripts/
│   ├── haina.py             # 海纳客户端
│   ├── store.py             # 本地状态
│   ├── rules.py             # 触发规则
│   └── watch.py             # CLI
├── data/schema.md           # 状态 schema
├── docs/VERIFICATION.md     # D1–D3 验证记录
├── fixtures/                # 离线演示数据
├── proxy/                   # 3–5 人内测代理（Cloudflare Worker）
│   ├── src/index.ts
│   ├── wrangler.toml
│   └── README.md
├── tests/                   # 单元/CLI/代理配置测试
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
