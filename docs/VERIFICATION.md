# D1–D3 验证记录

日期：2026-10-21  
环境：macOS，Python 3.14.6  
海纳 Key：测试 Key（未写入仓库；只存在 `~/.wishlist-watcher/.env.local`）

## 自动化测试

```bash
python3 -m unittest discover -s tests -v
```

结果：32 个测试全部通过。

覆盖：

- 价格解析（数字、货币字符串、范围拒绝）
- 目标价触发、跌破自入库最低价、未触发
- 24 小时冷却、再等等、截止时间过期
- 缺价格、商品未匹配时不提醒
- 状态读写、原子写入、UTF-8、ID 前缀
- 欢迎语首次/非首次
- 缺少 Key 的错误处理
- `feedback bought` 归档
- 非 active 项不检查
- 代理配置读写、环境变量覆盖、半配置报错
- 代理模式下使用 `/v1/product/search` + Bearer token

## 环境自检

```bash
python3 skills/wishlist-watcher/scripts/watch.py doctor --network
```

结果：通过。Python、状态目录、Key、fixtures、海纳网络均正常。

## 离线演示

```bash
python3 skills/wishlist-watcher/scripts/watch.py demo
```

结果：输出 2 个候选；目标价 9000 触发“达到目标价”，目标价 8000 不触发。

## 真实海纳调用

### 建档

```bash
python3 skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000 --format json
```

结果：`status=needs_pick`，返回多个候选（当时默认 10 个；现已改为默认 5 个）。

确认第 2 个（京东自营）后：

```bash
python3 skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2
```

结果：创建 `w_627211cae00a`，当前到手 ¥8,531.45，页面价 ¥10,129.00。

### 两步建档使用缓存的候选

```bash
python3 skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000 --state-dir <tmp>
HAINA_API_KEY="" python3 skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2 --state-dir <tmp>
```

结果：第一次 `needs_pick` 返回 5 个候选并写入 `pending-add.json`；第二次在无 Key、无网络的情况下用缓存候选建档成功，`pending-add.json` 自动删除。避免用户确认序号后重新搜索导致候选顺序变化。

### 不触发

```bash
python3 skills/wishlist-watcher/scripts/watch.py check --id w_627211cae00a --format json
```

结果：`not_met`，无提醒。

### 触发

用目标价 9000 另建一项：

```bash
python3 skills/wishlist-watcher/scripts/watch.py add "索尼 A7C2" --target 9000 --pick 2
python3 skills/wishlist-watcher/scripts/watch.py check --id w_6ccea569150e
```

结果：输出【值得买】卡片，原因 `target`，比目标价低 ¥468.55。

### 冷却

立即再次检查同一项：

```bash
python3 skills/wishlist-watcher/scripts/watch.py check --id w_6ccea569150e --format json
```

结果：`cooldown`，`cooldown_until` 为 24 小时后，无重复提醒。

### 反馈

```bash
python3 skills/wishlist-watcher/scripts/watch.py feedback w_6ccea569150e --action bought
python3 skills/wishlist-watcher/scripts/watch.py feedback w_627211cae00a --action wait --days 7
python3 skills/wishlist-watcher/scripts/watch.py feedback w_627211cae00a --action inaccurate --note "测试价格不准"
python3 skills/wishlist-watcher/scripts/watch.py feedback w_627211cae00a --action resume
```

结果：`bought` 归档；`wait` 设置 7 天冷却；`inaccurate` 暂停 1 天；`resume` 恢复 active。

## 便携性抽查

- 从 `/tmp` 运行绝对路径的 `demo`：通过。
- `--state-dir "/tmp/wishlist watcher test"`：欢迎语首次/非首次状态正确。
- 第二个工作目录执行 `list`：读取同一份默认状态成功。

## 内测代理代码验证

```bash
cd proxy
npm install
npm run typecheck
npx wrangler deploy --dry-run --outdir dist
```

结果：TypeScript 类型检查通过；Wrangler dry-run 成功打包，识别到 Durable Object、日上限、QPS、缓存 TTL 绑定。

本地 mock 代理验证：`WISHLIST_PROXY_URL` + `WISHLIST_PROXY_TOKEN` 指向本地 HTTP mock，`doctor --network` 返回 `mode=proxy`、`ok=true`，client 使用 `Bearer` 头和代理路径。

本地 `wrangler dev --local` 验证：`/healthz` 200；带邀请 token 的 `/v1/product/search` 返回 200、2 条真实海纳商品；`_meta.remaining=1999`，缓存/限流生效。

## 已部署

- Worker：`https://wishlist-watcher-proxy.huntingrin.workers.dev`
- Cloudflare 账号：`huntingrin@gmail.com`
- secrets：`HAINA_API_KEY`、`PROXY_TOKENS`（已通过 Cloudflare API 确认名称存在，值未记录）
- 部署版本：`cbda3372-02cc-4dbd-9840-735c40ee1f2a`

部署后从当前开发网络访问 `workers.dev` 出现 TLS handshake failure/timeout，未能从这台机器完成公网 smoke test；需要用内测用户网络或自定义域名复测。Worker 本地运行和 Cloudflare 部署本身均已成功。

## 大陆可达性诊断与自定义域（2026-10-22）

### 问题定位

`wishlist-watcher-proxy.huntingrin.workers.dev` 在大陆不可达，原因不是 Cloudflare 被封：

| 测试 | 结果 |
|---|---|
| 4 个公共 DNS 解析该域名 | 返回 4 个互不相同的垃圾 IP（31.13.95.17 等）→ DNS 投毒 |
| 用真实 IP + 原 SNI 直连 | TCP 建连成功，TLS 被 RST → `*.workers.dev` SNI 阻断 |
| 直连 Cloudflare 任意 IP（SNI=普通站点） | TLS 正常，0.25–0.6s → Cloudflare 网络本身可达 |

结论：换自定义域即可绕开。此前「本地验证通过」是因为开发机挂着 `127.0.0.1:7890` 代理（出口 `cf-ray: -CDG`），不代表大陆用户可达。

### 处置

- 注册 `huntingrin.com`（Cloudflare Registrar，3 年，$31.38），作为通用主域。
- Worker 绑定自定义域 `watch.huntingrin.com`（`wrangler.toml` 的 `routes`，`custom_domain = true`）。
- 客户端内置地址改为 `https://watch.huntingrin.com`（`DEFAULT_PROXY_URL`），测试同步更新。
- `workers_dev` 保留，仅供维护者挂代理调试。

### 复测清单

1. `npx wrangler deploy` 输出应包含 `watch.huntingrin.com (custom domain)`。
2. `curl https://watch.huntingrin.com/healthz` 返回 `{"ok":true,...}`。
3. 大陆 4G（移动/联通/电信各一）关代理访问同一地址。
4. 带邀请 token 调 `/v1/product/search` 返回真实商品。

### 实测结果（2026-10-22）

- 部署：`watch.huntingrin.com (custom domain)`，cert id `9e3226b9-…`，约 4 分钟后证书生效。
- 端到端（客户端 → 代理 → 海纳）：`login` → `setup` 返回 `mode=proxy, ready=true`；
  `add "索尼 A7C2" --target 9000 --pick 2` 创建 `w_0769b8db36db`；
  `check` 触发 `target`，到手 ¥8,590.95、页面价 ¥10,199.00，与直连模式一致。
- 大陆可达性（本机北京，不走代理）：**不稳定**。
  - 同一 Cloudflare IP、同一时间窗，仅换 SNI：`cloudflare.com` 8/8 成功；
    `watch.huntingrin.com` 4/8，成功时 2.6–6s，失败为 8s TCP 超时。
  - 连续 15 次 `healthz`：8 次成功。
  - 结论：不是 Cloudflare IP 或 Worker 的问题，是新域名的 SNI 被概率性丢包。
  - 挂代理访问时稳定；`*.workers.dev` 仍完全不可用。

### 已知限制

大陆网络下该域名可能一半请求超时。若内测用户反馈打不开，两条路：

1. 香港/新加坡轻量服务器，`watch.huntingrin.com` 改 A 记录直连（关闭橙色云朵），
   Worker 逻辑移植为 Node + 进程内限流，Caddy 自动签证书；
2. 阿里云函数计算（免备案默认域名），移植为 FC handler。

客户端支持 `WISHLIST_PROXY_URL` 或 `login --url` 覆盖地址，切换后端不需要重装 Skill。

## 已知未验证

- `new_low`（跌破自入库最低价）只在单元测试中验证，真实价格未出现更低点。
- 多平台同款匹配、券/活动条件、图搜/截图录入属于 D4。
- OpenCode 之外的宿主（Claude Code / Codex）实测属于 D5。
- 主动定时推送未接入；当前依赖宿主调用 `check`。

## v0.4 安装与 setup 验证

日期：2026-10-21

- `python3 -m unittest discover -s tests -v`：35 个测试全部通过。
- `npx skills add . --list`：从仓库根目录识别到 1 个 skill：`wishlist-watcher`。
- 在临时 `HOME` 中执行 `cat install.sh | bash -s -- --repo . --token invite-test-123456`（模拟 `curl | bash`）：
  - skill 安装到 `~/.agents/skills/wishlist-watcher`
  - `~/.wishlist-watcher/proxy.json` 写入成功，权限 0600
  - `setup` 返回 `ready=true`、`mode=proxy`
  - npx 步骤加了 `</dev/null`，否则会吞掉管道里剩余的安装脚本
- 未配置任何 token/Key 时执行 `setup --format json`：
  - 返回 `ready=false`、`reason=needs_data_source`
  - `next_action.type=login`，命令中不含 token
- `login --token ...` 不传 `--url` 时使用内置代理地址。
- `login --token ...` 输出不回显 token。

仍未验证：公网代理可达性（当前开发网络访问 `*.workers.dev` 超时）；跨 Claude Code / Codex 真机安装。

## 零配置 beta 通道

日期：2026-10-22

动机：朋友不该被要求「先找维护者要一个 token」。改为 Skill 内置公共 beta token。

- 新增 `skills/wishlist-watcher/beta-proxy.json`（url + token），随 `npx skills` 一起安装。
- 优先级：`WISHLIST_PROXY_*` 环境变量 > `~/.wishlist-watcher/proxy.json` > 自己的 `HAINA_API_KEY` > 内置 beta。
  有自己 Key 的开发者不会被自动切到代理。
- `install.sh` / `install.ps1` 的 `--token` 改为可选；不带 token 时不写 `proxy.json`。
- Worker 侧新增 `public-beta` token 到 `PROXY_TOKENS`，与邀请 token 共存。
- 测试数：37（新增「零配置即为 ready」和「自有 Key 优先于内置 beta」两条）。

验证（临时 `HOME` 模拟朋友机器）：

```bash
HOME=$(mktemp -d) bash install.sh --repo .
```

- `npx skills` 装到 `~/.agents/skills/wishlist-watcher`；
- 没有生成 `~/.wishlist-watcher/proxy.json`（符合零配置预期）；
- `setup` 返回 `ready=true`、`mode=proxy`、`proxy_url=https://watch.huntingrin.com`；
- 同一份安装执行 `add "索尼 A7C2" --target 9000 --pick 2` → `w_2d72ca6a7100`，
  `check` 触发 `target`，到手 ¥8,590.95。

风险与边界：内置 token 是公开凭证，任何人可从这个仓库拿到并使用；防线只有 Worker 的
`DAILY_LIMIT=2000` 和 `GLOBAL_QPS=4`。轮换方式见 `SECURITY.md`。
