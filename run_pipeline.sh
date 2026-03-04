#!/usr/bin/env bash
# -----------------------------------------------------------
# run_pipeline.sh — Interactive Markdown Translation CLI
# -----------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ANSI Colors for beautiful CLI
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
DIM='\033[2m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}   Markdown Translation & Formatting Tool   ${NC}"
echo -e "${BLUE}==============================================${NC}"

# Ensure source file is provided
if [ $# -gt 0 ]; then
  MD_FILE="$1"
else
  echo -e "${YELLOW}Please provide the path to the Markdown file:${NC}"
  read -p "> " MD_FILE
fi

if [ ! -f "$MD_FILE" ]; then
  echo -e "${RED}ERROR: File not found: '$MD_FILE'${NC}"
  exit 1
fi

echo -e "\n${GREEN}File selected:${NC} $MD_FILE"

# 1. Select Provider
AVAILABLE_JSON=$(python3 src/translators.py)
PROVIDER_SELECTION=$(python3 -c "
import sys, json

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = []

if not data:
    print('\033[0;31mERROR: No translators configured in .env\033[0m', file=sys.stderr)
    sys.exit(1)

print('\n\033[1;33mWhich translation provider would you like to prioritize?\033[0m', file=sys.stderr)
for i, t in enumerate(data, 1):
    others = [x['name'] for x in data if x['id'] != t['id']]
    fallback_str = (' (Auto-falls back to ' + ', '.join(others) + ' if needed)') if others else ''
    print(f'  {i}) {t[\"name\"]}{fallback_str}', file=sys.stderr)

print('', file=sys.stderr)
try:
    choice_str = input(f'Select [1-{len(data)}] (default: 1): ')
except BaseException:
    choice_str = ''

try:
    choice_idx = int(choice_str) - 1
    if choice_idx < 0 or choice_idx >= len(data):
        choice_idx = 0
except ValueError:
    choice_idx = 0

print(data[choice_idx]['id'])
" "$AVAILABLE_JSON")

if [ $? -ne 0 ]; then
    exit 1
fi

PROVIDER="$PROVIDER_SELECTION"
echo -e "Provider set to: ${GREEN}$PROVIDER${NC}"

# 2. Select Output Mode
echo -e "\n${YELLOW}Where do you want to generate the documents?${NC}"
echo "  1) Local only"
echo "  2) Google Drive only"
echo "  3) Both Local and Google Drive"
echo ""
read -p "Select [1-3] (default: 3): " DRIVE_CHOICE

DRIVE_FLAG=""
case "$DRIVE_CHOICE" in
  1) DRIVE_FLAG="" ;;
  2) DRIVE_FLAG="--drive --cloud-only" ;;
  *) DRIVE_FLAG="--drive" ;;
esac

echo -e "Google Drive generation: ${GREEN}$(if [ "$DRIVE_CHOICE" = "1" ]; then echo "OFF"; else echo "ON"; fi)${NC}"

# 3. Select Languages
# Read defaults from config.json
CONFIG_FILE="$SCRIPT_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
  CONFIG_FILE="$SCRIPT_DIR/config.example.json"
fi
DEFAULT_LANGS=$(python3 -c "
import json, sys
try:
    cfg = json.load(open('$CONFIG_FILE'))
    langs = cfg.get('document', {}).get('default_languages', ['EN','FR','AR','ZH'])
    print(' '.join(langs))
except: print('EN FR AR ZH')
" 2>/dev/null || echo "EN FR AR ZH")

echo -e "\n${YELLOW}Enter Target Language Codes separated by space:${NC}"
echo -e "  ${DIM}Supports ANY ISO code. Common examples: EN, FR, AR, ZH${NC}"
echo -e "  ${DIM}Leave empty to apply defaults (${DEFAULT_LANGS}).${NC}"
echo ""
read -p "> " LANGS_INPUT

if [ -z "$LANGS_INPUT" ]; then
  LANGS="$DEFAULT_LANGS"
else
  LANGS="$LANGS_INPUT"
fi
echo -e "Target languages: ${GREEN}$LANGS${NC}"

# Confirm and Run
echo -e "\n\n${BLUE}==============================================${NC}"
echo "Starting Translation Pipeline..."
echo -e "${BLUE}==============================================${NC}"

# Verify virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  echo -e "${RED}ERROR: Virtual environment not found. Please setup the project first.${NC}"
  exit 1
fi

# Activate virtual environment
source "$SCRIPT_DIR/.venv/bin/activate"

# Build command dynamically
CMD="python \"$SCRIPT_DIR/src/translation_pipeline.py\" \"$MD_FILE\" --provider \"$PROVIDER\" -l $LANGS"
if [ -n "$DRIVE_FLAG" ]; then
  CMD="$CMD $DRIVE_FLAG"
fi

if eval $CMD; then
  echo -e "\n${GREEN}Pipeline finished successfully!${NC}"
else
  echo -e "\n${RED}Pipeline finished with errors. Check the logs above.${NC}"
  # We don't exit 1 here if we want to allow the user to see the links/etc if any were generated, 
  # but since the python script already handled summary, we just echo.
fi
