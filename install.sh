#!/usr/bin/env bash
# One-command installer for the wishlist-watcher skill.
#
# Invite flow (recommended):
#   curl -fsSL https://raw.githubusercontent.com/huntingrin/wishlist-watcher/main/install.sh \
#     | bash -s -- --token invite-xxxx
#
# Already cloned locally:
#   bash install.sh --repo . --token invite-xxxx
#
set -euo pipefail

REPO="${WISHLIST_REPO:-huntingrin/wishlist-watcher}"
TOKEN="${WISHLIST_PROXY_TOKEN:-}"
URL="${WISHLIST_PROXY_URL:-}"
INSTALL_SKILL=1

usage() {
  cat <<'EOF'
用法：
  install.sh --token <邀请 token> [--url <代理地址>] [--repo <owner/repo|本地路径>]
  install.sh --help

选项：
  --token  邀请 token（必填；也可以先设置 WISHLIST_PROXY_TOKEN）
  --url    自建代理地址；默认使用内置地址
  --repo   技能来源，默认 huntingrin/wishlist-watcher
  --no-agent-install  只写代理配置，不安装 skill
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      TOKEN="${2:-}"
      shift 2
      ;;
    --token=*)
      TOKEN="${1#*=}"
      shift
      ;;
    --url)
      URL="${2:-}"
      shift 2
      ;;
    --url=*)
      URL="${1#*=}"
      shift
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --repo=*)
      REPO="${1#*=}"
      shift
      ;;
    --no-agent-install)
      INSTALL_SKILL=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$TOKEN" ]]; then
  echo "缺少邀请 token。用法：install.sh --token <邀请 token>" >&2
  exit 2
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(
        f"需要 Python 3.10+，当前是 {sys.version.split()[0]}。"
        "请先安装 Python，再重新运行安装命令。"
    )
PY

if [[ "$INSTALL_SKILL" -eq 1 ]]; then
  if ! command -v npx >/dev/null 2>&1; then
    echo "需要 Node.js 22.20+（用于 npx skills）。也可以手动安装见 docs/INSTALL.md。" >&2
    exit 1
  fi

  # Only target agents that look installed.  `npx skills -y` without this
  # also tries agents that do not support global installs (Eve/PromptScript)
  # and prints scary-looking failures even though installation succeeded.
  AGENT_ARGS=()
  if [[ -d "$HOME/.claude" ]]; then AGENT_ARGS+=(-a claude-code); fi
  if [[ -d "$HOME/.codex" ]]; then AGENT_ARGS+=(-a codex); fi
  if [[ -d "$HOME/.config/opencode" ]]; then AGENT_ARGS+=(-a opencode); fi
  if [[ -d "$HOME/.cursor" ]]; then AGENT_ARGS+=(-a cursor); fi
  if [[ -d "$HOME/.gemini" ]]; then AGENT_ARGS+=(-a gemini-cli); fi
  if [[ -d "$HOME/.copilot" ]]; then AGENT_ARGS+=(-a github-copilot); fi
  if [[ -d "$HOME/.codeium/windsurf" ]]; then AGENT_ARGS+=(-a windsurf); fi
  if [[ ${#AGENT_ARGS[@]} -eq 0 ]]; then
    # Universal install: canonical copy is enough; the user can add a
    # symlink for their agent later.
    AGENT_ARGS=(-a codex)
  fi

  # `< /dev/null` is required for `curl | bash`: npx must not consume the
  # remaining installer script from stdin.
  npx -y skills add "$REPO" --skill wishlist-watcher -g -y "${AGENT_ARGS[@]}" </dev/null
fi

# `npx skills` keeps a canonical copy under ~/.agents/skills and symlinks
# agent-specific directories to it.  Fall back to common agent paths for
# manual/copy installs.
SKILL_DIR=""
CANDIDATES=(
  "$HOME/.agents/skills/wishlist-watcher"
  "$HOME/.claude/skills/wishlist-watcher"
  "$HOME/.config/opencode/skills/wishlist-watcher"
  "$HOME/.codex/skills/wishlist-watcher"
  "$HOME/.cursor/skills/wishlist-watcher"
  "$HOME/.gemini/skills/wishlist-watcher"
)
for candidate in "${CANDIDATES[@]}"; do
  if [[ -f "$candidate/scripts/watch.py" ]]; then
    SKILL_DIR="$candidate"
    break
  fi
done

if [[ -z "$SKILL_DIR" ]]; then
  echo "没有找到安装后的 skill。请检查 npx skills 的输出，或手动安装见 docs/INSTALL.md。" >&2
  exit 1
fi

LOGIN_ARGS=(login --token "$TOKEN" --format json)
if [[ -n "$URL" ]]; then
  LOGIN_ARGS+=(--url "$URL")
fi
python3 "$SKILL_DIR/scripts/watch.py" "${LOGIN_ARGS[@]}" >/dev/null

echo
echo "安装完成：$SKILL_DIR"
python3 "$SKILL_DIR/scripts/watch.py" setup --format markdown
echo
echo "打开你的 agent，直接说：帮我盯 <商品>，降到 <目标价> 告诉我。"
