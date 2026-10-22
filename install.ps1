# One-command installer for the wishlist-watcher skill (Windows PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Token invite-xxxx
#
param(
  [string]$Token = "",
  [string]$Url = "",
  [string]$Repo = "huntingrin/wishlist-watcher"
)

$ErrorActionPreference = "Stop"

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
  throw "需要 Python 3.10+。请先安装 Python，再重新运行。"
}

$agentArgs = @()
if (Test-Path "$HOME\.claude") { $agentArgs += @("-a", "claude-code") }
if (Test-Path "$HOME\.codex") { $agentArgs += @("-a", "codex") }
if (Test-Path "$HOME\.config\opencode") { $agentArgs += @("-a", "opencode") }
if (Test-Path "$HOME\.cursor") { $agentArgs += @("-a", "cursor") }
if (Test-Path "$HOME\.gemini") { $agentArgs += @("-a", "gemini-cli") }
if ($agentArgs.Count -eq 0) { $agentArgs = @("-a", "codex") }

npx -y skills add $Repo --skill wishlist-watcher -g -y @agentArgs
if ($LASTEXITCODE -ne 0) { throw "npx skills 安装失败" }

$candidates = @(
  "$HOME\.agents\skills\wishlist-watcher",
  "$HOME\.claude\skills\wishlist-watcher",
  "$HOME\.config\opencode\skills\wishlist-watcher",
  "$HOME\.codex\skills\wishlist-watcher",
  "$HOME\.cursor\skills\wishlist-watcher"
)
$skillDir = $candidates | Where-Object { Test-Path (Join-Path $_ "scripts\watch.py") } | Select-Object -First 1
if (-not $skillDir) {
  throw "没有找到安装后的 skill。请查看 docs/INSTALL.md 手动安装。"
}

if ($Url -and -not $Token) { throw "-Url 需要同时提供 -Token" }
if ($Token) {
  $loginArgs = @((Join-Path $skillDir "scripts\watch.py"), "login", "--token", $Token, "--format", "json")
  if ($Url) { $loginArgs += @("--url", $Url) }
  python @loginArgs | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "写入代理配置失败" }
} else {
  Write-Host "使用 skill 内置的 beta 通道，无需额外配置。"
}

Write-Host ""
Write-Host "安装完成：$skillDir"
python (Join-Path $skillDir "scripts\watch.py") setup --format markdown
Write-Host ""
Write-Host "打开你的 agent，直接说：帮我盯 <商品>，降到 <目标价> 告诉我。"
