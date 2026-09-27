#!/usr/bin/env bash
# gpt6-sol-vs-luna Linux/WSL setup check. Never installs silently.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== gpt6-sol-vs-luna setup (linux/wsl) =="
echo "project: $ROOT"
check() { if command -v "$1" >/dev/null 2>&1; then echo "[OK] $1: $($2 2>&1 | head -1)"; else echo "[MISS] $1 -- $3"; fi }
check python3 "python3 --version" "apt install python3.11 python3-venv / pyenv"
check git "git --version" "apt install git"
check docker "docker --version" "install docker + add user to docker group"
docker info >/dev/null 2>&1 && echo "[OK] docker daemon" || echo "[MISS] docker daemon -- sudo systemctl start docker"
check node "node --version" "install Node.js LTS (needed for OpenCode)"
check opencode "opencode --version" "npm install -g opencode-ai, then opencode providers login"
command -v opencode >/dev/null && opencode models 2>/dev/null | head -12 || echo "[INFO] opencode models unavailable -- login first"
echo ""
echo "Model access is via your OpenCode account/provider (no keys stored in repo)."
echo "Confirm openai/gpt-6-sol and openai/gpt-6-luna in 'opencode models'; non-fast variants only."
echo ""
echo "next: cd '$ROOT'; pip install -e .; python -m context_bench doctor"
