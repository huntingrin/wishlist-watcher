# Wishlist Watcher Proxy

给 3–5 人内部测试用的最小代理。海纳 Key 只放在 Cloudflare Worker 的 secret 里，客户端只拿邀请 token。

## 它做什么

```text
Skill  →  Bearer <invite-token>  →  Worker  →  x-api-key  →  海纳
```

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查，无鉴权 |
| POST | `/v1/product/search` | 转发到海纳 `product/v1` |
| POST | `/v1/discount/search` | 转发到海纳 `hj-search/discount/v2` |

安全阀：

- `PROXY_TOKENS`：邀请 token → 测试者名称的 JSON map
- 全局日上限：`DAILY_LIMIT`，默认 2000
- 全局 QPS：`GLOBAL_QPS`，默认 4（低于海纳单 Key 5 QPS）
- 响应缓存：`CACHE_TTL_SECONDS`，默认 300 秒，仅 isolate 内 best-effort
- 请求体上限 8 KB，`product_query` 最长 100 字，`size` 1–10
- 不记录 query 内容、token、Haina Key

## 当前内测部署

```text
https://wishlist-watcher-proxy.huntingrin.workers.dev
```

已设置 `HAINA_API_KEY`、`PROXY_TOKENS` 两个 secret。邀请 token 由维护者私下分发，不写入仓库。

部分网络无法访问 `*.workers.dev`（TLS handshake failure / timeout）。如果内测用户打不开，需要：

1. 给 Worker 绑定一个自定义域名（需要域名已接入 Cloudflare）；或
2. 把同一份 `src/index.ts` 部署到 VPS/Fly.io 等可访问的运行时。

## 部署

```bash
cd proxy
npm install
npx wrangler login
```

设置两个 secret（命令会提示输入，不会进 shell 历史）：

```bash
npx wrangler secret put HAINA_API_KEY
npx wrangler secret put PROXY_TOKENS
```

`PROXY_TOKENS` 的值是一个 JSON map，例如：

```json
{"invite-alice-7f3a9c":"alice","invite-bob-2d8e1b":"bob"}
```

邀请 token 请用长随机字符串，不要用 `test123`。

部署：

```bash
npm run deploy
```

输出里会有：

```text
https://wishlist-watcher-proxy.<your-subdomain>.workers.dev
```

## 给测试者发安装命令

每个测试者一个 token，发这一条（替换 token）：

```bash
curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh \
  | bash -s -- --token invite-alice-xxxxxxxx
```

脚本会自动安装 skill、写入代理配置并运行 `setup`。测试者不需要接触海纳 Key。

## 自测

```bash
export PROXY_URL="https://wishlist-watcher-proxy.<subdomain>.workers.dev"
export PROXY_TOKEN="invite-alice-..."

curl -s "$PROXY_URL/healthz"

curl -s "$PROXY_URL/v1/product/search" \
  -H "Authorization: Bearer $PROXY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"product_query":"索尼 A7C2","request_from":"proxy-smoke","question_id":"smoke-1","size":2}'
```

## 改配额/保险丝

编辑 `wrangler.toml`：

```toml
[vars]
DAILY_LIMIT = "2000"
GLOBAL_QPS = "4"
CACHE_TTL_SECONDS = "300"
```

然后 `npm run deploy`。改 `PROXY_TOKENS` 只需要重新执行 `wrangler secret put`，不用改代码。

## 轮换 Key / Token

- Haina Key 轮换：`npx wrangler secret put HAINA_API_KEY`，输入新 Key，立即生效。
- 邀请 token 轮换：更新 `PROXY_TOKENS` JSON，删除旧 token 后再 `wrangler secret put`。
- 不要在 Issue、聊天、截图中粘贴真实 token 或 Key。

## 成本

- Worker 免费版通常够 3–5 人测试。
- 付费版约 $5/月。
- 海纳调用费另算，取决于海纳商务报价。

## 合规

公网代理属于“用自己的 Key 向第三方提供海纳数据”。公开运营前，先向海纳确认是否允许代理、是否需要商务合同/计费。内部测试也建议先发一封邮件说明范围。

## 文件

```text
src/index.ts        Worker 入口 + RateLimiter Durable Object
wrangler.toml       绑定、迁移、保险丝配置
.dev.vars.example   本地开发变量示例（真实值不要提交）
```
