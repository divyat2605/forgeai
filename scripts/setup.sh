#!/usr/bin/env bash
# ForgeAI one-time setup on macOS / Linux.   ./scripts/setup.sh [standard|laptop|tiny]
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${1:-standard}"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"; print("Python", sys.version.split()[0])'
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -e ".[dev]" --quiet
command -v ollama >/dev/null || { echo "Install Ollama from https://ollama.com and start it, then re-run."; exit 1; }
case "$PROFILE" in
  standard) MODELS="qwen3:8b gemma3:4b nomic-embed-text" ;;
  laptop)   MODELS="qwen3:4b gemma3:4b nomic-embed-text" ;;
  tiny)     MODELS="qwen3:1.7b gemma3:4b nomic-embed-text" ;;
esac
for m in $MODELS; do ollama pull "$m"; done
.venv/bin/python -m pytest -q
.venv/bin/forge doctor --profile "$PROFILE"
echo "Ready: source .venv/bin/activate && forge build --help"
