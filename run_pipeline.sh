#!/usr/bin/env bash
# -----------------------------------------------------------
# run_pipeline.sh — Wrapper for the Markdown Translation Tool
# -----------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ANSI Colors for errors
RED='\033[1;31m'
NC='\033[0m' # No Color

# Check pandoc
if ! command -v pandoc >/dev/null 2>&1; then
  echo -e "${RED}ERROR: Pandoc is not installed.${NC}"
  echo "Install it first:"
  echo "  brew install pandoc   (mac)"
  echo "  sudo apt install pandoc   (linux)"
  exit 1
fi

# Verify virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  echo -e "${RED}ERROR: Virtual environment not found. Please run 'python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt' first.${NC}"
  exit 1
fi

# Activate virtual environment
source "$SCRIPT_DIR/.venv/bin/activate"

# Pass all arguments exactly as they were provided down to the Python script
exec python -m src.cli.main "$@"
