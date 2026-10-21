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
python3 scripts/watch.py doctor --network
```

结果：通过。Python、状态目录、Key、fixtures、海纳网络均正常。

## 离线演示

```bash
python3 scripts/watch.py demo
```

结果：输出 2 个候选；目标价 9000 触发“达到目标价”，目标价 8000 不触发。

## 真实海纳调用

### 建档

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 8000 --format json
```

结果：`status=needs_pick`，返回多个候选（当时默认 10 个；现已改为默认 5 个）。

确认第 2 个（京东自营）后：

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2
```

结果：创建 `w_627211cae00a`，当前到手 ¥8,531.45，页面价 ¥10,129.00。

### 两步建档使用缓存的候选

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 8000 --state-dir <tmp>
HAINA_API_KEY="" python3 scripts/watch.py add "索尼 A7C2" --target 8000 --pick 2 --state-dir <tmp>
```

结果：第一次 `needs_pick` 返回 5 个候选并写入 `pending-add.json`；第二次在无 Key、无网络的情况下用缓存候选建档成功，`pending-add.json` 自动删除。避免用户确认序号后重新搜索导致候选顺序变化。

### 不触发

```bash
python3 scripts/watch.py check --id w_627211cae00a --format json
```

结果：`not_met`，无提醒。

### 触发

用目标价 9000 另建一项：

```bash
python3 scripts/watch.py add "索尼 A7C2" --target 9000 --pick 2
python3 scripts/watch.py check --id w_6ccea569150e
```

结果：输出【值得买】卡片，原因 `target`，比目标价低 ¥468.55。

### 冷却

立即再次检查同一项：

```bash
python3 scripts/watch.py check --id w_6ccea569150e --format json
```

结果：`cooldown`，`cooldown_until` 为 24 小时后，无重复提醒。

### 反馈

```bash
python3 scripts/watch.py feedback w_6ccea569150e --action bought
python3 scripts/watch.py feedback w_627211cae00a --action wait --days 7
python3 scripts/watch.py feedback w_627211cae00a --action inaccurate --note "测试价格不准"
python3 scripts/watch.py feedback w_627211cae00a --action resume
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

## 已知未验证

- `new_low`（跌破自入库最低价）只在单元测试中验证，真实价格未出现更低点。
- 多平台同款匹配、券/活动条件、图搜/截图录入属于 D4。
- OpenCode 之外的宿主（Claude Code / Codex）实测属于 D5。
- 主动定时推送未接入；当前依赖宿主调用 `check`。
- 当前开发网络无法访问 `*.workers.dev`，公网 smoke test 需要用用户网络或自定义域名复测。
