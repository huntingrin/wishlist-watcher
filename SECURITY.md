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

## 报告问题

请通过 GitHub Security Advisory 私下报告，不要在公开 Issue 中粘贴 Key、token 或完整请求头。

## 数据与隐私

- 监控项保存在用户本地；仓库不收集用户数据。
- 代理模式会经服务端转发查询；部署者应提供隐私说明，并限制日志保留时间。
