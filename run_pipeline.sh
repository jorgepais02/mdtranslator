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

# Check pandoc
if ! command -v pandoc >/dev/null 2>&1; then
  echo -e "${RED}ERROR: Pandoc is not installed.${NC}"
  echo "Install it first:"
  echo "  brew install pandoc   (mac)"
  echo "  sudo apt install pandoc   (linux)"
  exit 1
fi

# Parse Arguments
VERBOSE="N"
MD_FILE=""

for arg in "$@"; do
  if [[ "$arg" == "-v" || "$arg" == "--verbose" ]]; then
    VERBOSE="Y"
  elif [[ -z "$MD_FILE" && "$arg" != -* ]]; then
    MD_FILE="$arg"
  fi
done

# Ensure source file is provided
if [ -z "$MD_FILE" ]; then
  echo -e "${YELLOW}Please provide the path to the Markdown file:${NC}"
  read -p "> " MD_FILE
fi

if [ ! -f "$MD_FILE" ]; then
  echo -e "${RED}ERROR: File not found: '$MD_FILE'${NC}"
  exit 1
fi

echo -e "\n${GREEN}File selected:${NC} $MD_FILE"

# 1. Provide Context & Auto-formatting
if [[ "$MD_FILE" == *.txt ]]; then
  echo -e "\n${YELLOW}It looks like you provided a raw text file (.txt).${NC}"
  echo "Would you like to use Gemini AI to format it into clean, structured Markdown automatically?"
  echo "  1) Yes, format it (Requires GEMINI_API_KEY in .env)"
  echo "  2) No, use it as is"
  echo ""
  read -p "Select [1-2] (default: 1): " FORMAT_CHOICE
  
  if [ "$FORMAT_CHOICE" != "2" ]; then
    echo -e "\n${BLUE}==============================================${NC}"
    echo "Formatting text with Gemini AI..."
    echo -e "${BLUE}==============================================${NC}"
    
    # Needs virtual environment
    if [ ! -d "$SCRIPT_DIR/.venv" ]; then
      echo -e "${RED}ERROR: Virtual environment not found. Please setup the project first.${NC}"
      exit 1
    fi
    source "$SCRIPT_DIR/.venv/bin/activate"
    
    if python "$SCRIPT_DIR/src/generate_markdown.py" "$MD_FILE"; then
      MD_FILE="${MD_FILE%.*}.md"
      echo -e "${GREEN}Successfully formatted. New source file:${NC} $MD_FILE"
    else
      echo -e "\n${RED}Formatting failed. Continuing with original file...${NC}"
    fi
  fi
fi

# 2. Select Provider
AVAILABLE_JSON=$(python3 src/translators.py)

# Parse translators and display options
echo -e "\n${YELLOW}Which translation provider would you like to prioritize?${NC}"
python3 -c "
import sys, json
try:
    data = json.loads(sys.argv[1])
    if not data: sys.exit(1)
    for i, t in enumerate(data, 1):
        others = [x['name'] for x in data if x['id'] != t['id']]
        fallback_str = (' (Auto-falls back to ' + ', '.join(others) + ' if needed)') if others else ''
        print(f'  {i}) {t[\"name\"]}{fallback_str}')
except Exception:
    sys.exit(1)
" "$AVAILABLE_JSON" || { echo -e "${RED}ERROR: No translators configured in .env${NC}"; exit 1; }

echo ""
# Get the max number of options
OPT_COUNT=$(echo "$AVAILABLE_JSON" | grep -o '\"id\"' | wc -l | tr -d ' ')
read -p "Select [1-$OPT_COUNT] (default: 1): " PROVIDER_CHOICE

# Get id based on choice 
PROVIDER=$(python3 -c "
import sys, json
try:
    data = json.loads(sys.argv[1])
    idx = int(sys.argv[2]) - 1 if sys.argv[2] else 0
    if idx < 0 or idx >= len(data): idx = 0
    print(data[idx]['id'])
except Exception:
    print('azure') # solid fallback
" "$AVAILABLE_JSON" "$PROVIDER_CHOICE")

echo -e "Provider set to: ${GREEN}$PROVIDER${NC}"

# 3. Select Output Mode
echo -e "\n${YELLOW}Where should the generated DOCX files be stored?${NC}"
echo "  1) Local only"
echo "  2) Google Drive only"
echo "  3) Both Local and Google Drive"
echo ""
read -p "Select [1-3] (default: 3): " DRIVE_CHOICE

DRIVE_FLAG=""
case "$DRIVE_CHOICE" in
  1) DRIVE_FLAG="" ;;
  # Notice: we no longer use --cloud-only (which skipped local DOCX generation)
  # because Drive direct upload requires a locally generated DOCX first.
  # So "Google Drive only" just implies we don't necessarily keep local copies or perhaps
  # we still pass --no-local but `translation_pipeline.py` handles it transparently.
  # Our translation_pipeline.py DOES accept --no-local but it STILL generates the local DOCX when --drive is set.
  2) DRIVE_FLAG="--drive --cloud-only" ;;
  *) DRIVE_FLAG="--drive" ;;
esac

echo -e "Google Drive upload: ${GREEN}$(if [ "$DRIVE_CHOICE" = "1" ]; then echo "OFF"; else echo "ON"; fi)${NC}"

# 4. Select Languages
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
LANGS=$(echo "$LANGS" | tr '[:lower:]' '[:upper:]' | tr ' ' '\n' | grep -E '^[A-Z]{2,3}$' | tr '\n' ' ')
echo -e "Target languages: ${GREEN}$LANGS${NC}"

# Confirm and Run
echo -e "\n\n${BLUE}==============================================${NC}"
echo "Starting Translation Pipeline..."
echo -e "${DIM}Output format: DOCX (academic template via Pandoc)${NC}"
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

if [[ "$VERBOSE" =~ ^[Yy]$ ]]; then
  CMD="$CMD --verbose"
fi

if bash -c "$CMD"; then
  echo -e "\n${GREEN}Pipeline finished successfully!${NC}"
else
  echo -e "\n${RED}Pipeline finished with errors. Check the logs above.${NC}"
  # We don't exit 1 here if we want to allow the user to see the links/etc if any were generated, 
  # but since the python script already handled summary, we just echo.
fi
