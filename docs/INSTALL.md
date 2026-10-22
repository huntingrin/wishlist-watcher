# 安装与首次运行

目标：朋友拿到一条安装命令后，不需要理解海纳、不需要手写配置文件，就能让任意 Agent 开始盯价。

## 1. 推荐：零配置一条命令

```bash
curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh | bash
```

脚本会：

1. 检查 Python 3.10+。
2. 用 `npx skills` 安装 `skills/wishlist-watcher/` 到已检测到的 agent。
3. 运行 `setup` 并打印就绪状态。

Skill 自带 `beta-proxy.json`（公共 beta token，非密钥），所以不需要维护者发任何东西。
海纳 Key 和上游地址始终只在 Worker secret 里。

### 用单独发的 token（可单独撤销）

```bash
curl -fsSL .../install.sh | bash -s -- --token invite-xxxx
```

也可以先 `export WISHLIST_PROXY_TOKEN=invite-xxxx`，再运行 `bash install.sh`，避免 token 进 shell 历史。

装完直接对 agent 说：

```text
帮我盯 索尼 A7C2，降到 8000 告诉我
```

### 自建代理

```bash
curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh \
  | bash -s -- --token invite-xxxx --url https://your-proxy.example
```

### Windows

```powershell
# 先下载脚本
Invoke-WebRequest https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.ps1 -OutFile install.ps1

powershell -ExecutionPolicy Bypass -File install.ps1 -Token invite-xxxx
```

## 2. 手动安装 Skill

### 用 npx skills（推荐）

```bash
# 全局安装到已检测到的 agent
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y

# 只装到 Claude Code
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y -a claude-code

# 只装到 Codex
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y -a codex

# 只装到 OpenCode
npx skills add huntingrin/wishlist-watcher --skill wishlist-watcher -g -y -a opencode
```

`npx skills` 会把 canonical 副本放在 `~/.agents/skills/wishlist-watcher`，再给各 agent 建软链接。

如果输出里出现 `Eve` / `PromptScript` 的 “does not support global skill installation”，那是这两个宿主不支持全局安装，不影响其他 agent；也可以只用 `-a claude-code` 之类指定宿主。

更新：

```bash
npx skills update wishlist-watcher -g
```

### 直接复制

把 `skills/wishlist-watcher/` 整个目录复制到宿主的全局 skills 目录：

| 宿主 | 全局目录 |
|---|---|
| Claude Code | `~/.claude/skills/wishlist-watcher/` |
| Codex / Cline / Zed | `~/.agents/skills/wishlist-watcher/` |
| OpenCode | `~/.config/opencode/skills/wishlist-watcher/` |
| Cursor | `~/.cursor/skills/wishlist-watcher/` |
| Gemini CLI | `~/.gemini/skills/wishlist-watcher/` |
| GitHub Copilot | `~/.copilot/skills/wishlist-watcher/` |
| Windsurf | `~/.codeium/windsurf/skills/wishlist-watcher/` |

项目级安装把目录放到项目的 `.agents/skills/`、`.claude/skills/` 等即可。

## 3. 配置数据源

### 邀请 token（可选，覆盖内置 beta）

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py login --token "invite-xxxx"
```

只写 token 即可，代理地址已内置。自建代理加 `--url`。

token 等同于密码：

- 不要提交到仓库、Issue、聊天截图。
- 保存在 `~/.wishlist-watcher/proxy.json`（`0600`）。
- 怀疑泄露时让维护者轮换 `PROXY_TOKENS`。

### 海纳 Key（直连）

```bash
export HAINA_API_KEY="你的 Key"
```

或写入 `~/.wishlist-watcher/.env.local`：

```text
HAINA_API_KEY=...
```

不要把 Key 放进 Skill 目录或仓库。

## 4. 确认就绪

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py setup --format json
```

`ready=true` 才算可用。`ready=false` 时只看 `next_action`：

| `reason` | 含义 | 处理 |
|---|---|---|
| `needs_data_source` | 内置通道被移除且没有 token/Key | 运行 `login --token ...` 或设置 `HAINA_API_KEY` |
| `proxy_config_invalid` | `proxy.json` 损坏 | 先 `logout`，再重新 `login` |
| `python_too_old` | Python < 3.10 | 安装新 Python |
| `state_dir_unwritable` | 状态目录不可写 | 用 `--state-dir` 换目录 |

联网自检：

```bash
python3 ~/.agents/skills/wishlist-watcher/scripts/watch.py doctor --network
```

## 5. 常见问题

### agent 找不到 skill

- 确认文件在：`~/.agents/skills/wishlist-watcher/SKILL.md`
- 重启 agent 会话。
- Claude Code 可用 `/skills` 查看；OpenCode 用 `skill` 工具列表确认。
- 如果用了 `npx skills`，运行 `npx skills list -g` 检查安装路径。

### `npx skills` 报 Node 版本不够

需要 Node.js 22.20+。升级 Node，或者直接手动复制目录。

### 无法访问 `*.workers.dev`

`*.workers.dev` 在大陆网络被阻断（DNS 投毒 + TLS SNI 重置），这不是配置问题。
内测请使用自定义域 `https://watch.huntingrin.com`；安装脚本已内置该地址，正常不需要手动指定。

如果自定义域也不通，按 `proxy/README.md` 的备选方案处理。

### 提示 token 无效（401）

- 找维护者确认 token 还在 `PROXY_TOKENS` 里。
- 重新运行 `login --token ...`。
- 不要反复重试，401 不会自己恢复。

### 跨 agent 状态不连续

所有 agent 默认共用 `~/.wishlist-watcher/watchlist.json`。如果用了 `--state-dir`，要确保每个 agent 都指向同一个目录。

## 6. 给维护者：生成邀请命令

1. 在 `proxy/` 下更新 `PROXY_TOKENS` secret（JSON map，见 `proxy/README.md`）。
2. 给每个朋友生成一个长随机 token。
3. 发这一条（把 token 替换掉）：

```bash
curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh \
  | bash -s -- --token invite-alice-xxxxxxxx
```

4. 让朋友运行后把 `setup --format json` 的输出发回来确认 `ready=true`。

不要把 token 直接写进仓库的 README、Issue 模板或示例命令。
