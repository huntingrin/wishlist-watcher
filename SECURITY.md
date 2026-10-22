# Security

## 不提交密钥

本仓库不包含任何海纳 API Key、代理邀请 token 或用户数据。

- 直连模式：Key 只从 `HAINA_API_KEY` 环境变量或 `~/.wishlist-watcher/.env.local` 读取。
- 内测代理：海纳 Key 只存在 Cloudflare Worker secret；客户端只保存邀请 token 到 `~/.wishlist-watcher/proxy.json`（0600）。
- `.env.local`、`proxy.json`、`proxy/.dev.vars`、`proxy/node_modules` 均已加入 `.gitignore`。

## 如果密钥泄露

1. 立即在海纳工作台轮换/失效 Key。
2. 如果泄露的是代理邀请 token，更新 Worker 的 `PROXY_TOKENS` secret，删除旧 token。
3. 如果已经提交到 git，删除历史 commit 不够；必须按平台流程清理历史，并视为已泄露。
4. 检查代理用量和异常请求。

## 代理服务

- `HAINA_API_KEY` 和 `PROXY_TOKENS` 只通过 `wrangler secret put` 设置，不写进 `wrangler.toml`。
- Worker 日志不记录 token、Key、完整 query。
- 代理只在内部测试使用；公开运营前需确认海纳授权、隐私政策和计费。

## 仓库里没有凭证

`skills/wishlist-watcher/beta-proxy.json` 只有代理地址，**不含任何 token**。

客户端首次使用时的流程：

1. `POST /v1/session {"client_id": "<本地随机 id>"}`
2. Worker 校验 `SESSION_SECRET`，签发 `w1.<payload>.<hmac>` 形式的通行证（默认 30 天）
3. 客户端存到 `~/.wishlist-watcher/session.json`（0600），过期或 401 时自动续签

因此：

- 仓库、git 历史、skill 包里都没有可重放的凭证。拿到代码的人无法直接调用代理。
- 通行证是无状态签名，服务端不存库；`SESSION_SECRET` 轮换即全部失效。
- `/v1/session` 按 IP 限速（默认 10 次/小时），防止被批量申请。
- 海纳 Key 和上游地址仍然只在 Worker secret 里。
- 旧的静态邀请 token（`PROXY_TOKENS`）保留，用于需要单独吊销的人；优先级高于通行证。
- 记录（2026-10-23）：移除随仓库分发的静态 beta token，改为云端签发通行证；
  旧静态值验证为 401。

## 报告问题

请通过 GitHub Security Advisory 私下报告，不要在公开 Issue 中粘贴 Key、token 或完整请求头。

## 数据与隐私

- 监控项保存在用户本地；仓库不收集用户数据。
- 代理模式会经服务端转发查询；部署者应提供隐私说明，并限制日志保留时间。
