#Requires -Version 5.1
<#
.SYNOPSIS
  gpt6-sol-vs-luna setup check (Docker Desktop + WSL2 + OpenCode path).
  Never installs anything silently; prints exact fix instructions.
#>
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Write-Host "== gpt6-sol-vs-luna setup (Windows) ==" -ForegroundColor Cyan
Write-Host "project: $root"

function Check($name, $cmd, $fix) {
  try {
    $v = & $cmd 2>&1 | Select-Object -First 1
    if ($LASTEXITCODE -eq 0 -or $v) { Write-Host "[OK] $name : $v" -ForegroundColor Green }
    else { Write-Host "[MISS] $name -- $fix" -ForegroundColor Yellow }
  } catch { Write-Host "[MISS] $name -- $fix" -ForegroundColor Yellow }
}

Check "Python 3.10+" { python --version } "Install Python 3.11+ from python.org and re-open terminal."
Check "git" { git --version } "Install Git for Windows."
Check "Docker" { docker --version } "Install Docker Desktop, enable WSL2 backend, start Docker Desktop."
Check "Docker daemon" { docker info --format '{{.ServerVersion}}' } "Start Docker Desktop and wait for green status."
Check "Node.js" { node --version } "Install Node.js LTS (needed for OpenCode)."
Check "OpenCode" { opencode --version } "npm install -g opencode-ai  (then opencode providers login)"
Check "OpenCode models" { opencode models } "Run 'opencode providers login' so GPT-6 Sol/Luna appear; see config/models.yaml."
Check "WSL" { wsl --status } "Optional: wsl --install  (needed for Docker Desktop backend on Win10)."

Write-Host ""
Write-Host "Model access is via your OpenCode account/provider (no keys stored in repo)."
Write-Host "Confirm openai/gpt-6-sol and openai/gpt-6-luna in 'opencode models'; non-fast variants only."
Write-Host ""
Write-Host "next: cd '$root'; pip install -e .; python -m context_bench doctor"
