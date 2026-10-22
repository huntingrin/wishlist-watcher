# Wishlist Watcher Proxy

给 3–5 人内部测试用的最小代理。海纳 Key 只放在 Cloudflare Worker 的 secret 里；
客户端默认用 Skill 内置的公共 beta token，也支持单独发的邀请 token。

## 它做什么

```text
Skill  →  Bearer <invite-token>  →  Worker  →  x-api-key  →  海纳
```

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查，无鉴权 |
| POST | `/v1/session` | 签发短期通行证（按 IP 限速，无凭证） |
| POST | `/v1/product/search` | 转发到海纳 `product/v1`（需 Bearer） |
| POST | `/v1/discount/search` | 转发到海纳 `hj-search/discount/v2`（需 Bearer） |

### 凭证模型

仓库里不放任何 token。客户端首次调用前先 `POST /v1/session`：

```json
{"client_id": "本机随机 id"}
```

响应：

```json
{"token": "w1.<payload>.<hmac>", "expires_at": "2026-11-22T00:00:00Z", "ttl_seconds": 2592000}
```

- token 是无状态签名（HMAC-SHA256，`SESSION_SECRET`），服务端不存库。
- 默认 30 天，`SESSION_TTL_DAYS` 可调；`SESSION_PER_HOUR` 控制每 IP 每小时可申请次数。
- 轮换 `SESSION_SECRET` 会让所有已签发的通行证立即失效。
- `PROXY_TOKENS` 里的静态 token 仍然可用，优先级高于通行证，适合需要单独吊销的人。

安全阀：

- `PROXY_TOKENS`：邀请 token → 测试者名称的 JSON map
- 全局日上限：`DAILY_LIMIT`，默认 2000
- 全局 QPS：`GLOBAL_QPS`，默认 4（低于海纳单 Key 5 QPS）
- 响应缓存：`CACHE_TTL_SECONDS`，默认 300 秒，仅 isolate 内 best-effort
- 请求体上限 8 KB，`product_query` 最长 100 字，`size` 1–10
- 不记录 query 内容、token、Haina Key

## 当前内测部署

```text
https://watch.huntingrin.com        # 内测用户走这个（自定义域）
https://wishlist-watcher-proxy.huntingrin.workers.dev   # 仅维护者调试
```

已设置 `HAINA_API_KEY`、`PROXY_TOKENS` 两个 secret。
其中有一个 token 标为 `public-beta`，写在 `skills/wishlist-watcher/beta-proxy.json` 里随仓库公开，
目的是让朋友零配置安装。它只用于需要单独吊销的人；默认路径是 `/v1/session` 动态签发。

大陆网络会阻断 `*.workers.dev`（DNS 投毒 + TLS SNI 重置），所以内测统一走
`watch.huntingrin.com`；`workers_dev` 保留只为维护者挂代理时调试。

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

默认什么都不用发，让测试者直接跑：

```bash
curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh | bash
```

想给某人单独的、可单独撤销的 token 时，才发带 `--token` 的版本：

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
- 邀请 token 轮换：更新 `PROXY_TOKENS` JSON，删除旧 token 后再 `wrangler secret put`；
  公共 beta token 轮换后还要更新 `skills/wishlist-watcher/beta-proxy.json` 并提交。
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
