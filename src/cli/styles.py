import sys
import questionary
from rich.console import Console

console = Console()

def elide(texto: str, cabe: int) -> str:
    """Recorta por el final dejando puntos suspensivos. Nunca devuelve mas de `cabe`."""
    if cabe <= 1:
        return texto[:max(0, cabe)]
    return texto if len(texto) <= cabe else texto[:cabe - 1] + "\u2026"


def clear_screen():
    """Clear terminal screen synchronously through Python's stdout buffer."""
    sys.stdout.flush()
    sys.stdout.write('\033[H\033[2J\033[3J')
    sys.stdout.flush()

# ── Exact color tokens from Lovable index.css (HSL → hex) ────────────────────
GREEN   = "#47d179"
BLUE    = "#47a1ea"
YELLOW  = "#f4b73d"
RED     = "#dc3b3b"
CYAN    = "#47d1d1"
MAGENTA = "#b770db"
DIM     = "#5b6270"
BRIGHT  = "#e8e9ec"
FG      = "#d4d7dc"

# ── questionary style ─────────────────────────────────────────────────────────
# qmark ""  → hides the "?" completely
# pointer ❯ → matches the Lovable mock
WIZARD_STYLE = questionary.Style([
    ("qmark",       "fg:#47a1ea"),          # "?" — make it same color as question so it blends
    ("question",    f"fg:{BRIGHT} bold"),
    ("answer",      f"fg:{GREEN} bold"),
    ("pointer",     f"fg:{GREEN} bold"),    # ❯
    ("highlighted", f"fg:{GREEN}"),
    ("selected",    f"fg:{GREEN} bold"),
    ("instruction", f"fg:{DIM} italic"),
    ("separator",   f"fg:{DIM}"),
    ("text",        f"fg:{FG}"),
])

# ── Language glossary ─────────────────────────────────────────────────────────
LANGUAGES = {
    "EN": {"name": "English",    "rtl": False, "refine": False},
    "ES": {"name": "Spanish",    "rtl": False, "refine": False},
    "FR": {"name": "French",     "rtl": False, "refine": False},
    "DE": {"name": "German",     "rtl": False, "refine": False},
    "IT": {"name": "Italian",    "rtl": False, "refine": False},
    "PT": {"name": "Portuguese", "rtl": False, "refine": False},
    "RU": {"name": "Russian",    "rtl": False, "refine": False},
    "JA": {"name": "Japanese",   "rtl": False, "refine": True},
    "KO": {"name": "Korean",     "rtl": False, "refine": True},
    "ZH": {"name": "Chinese",    "rtl": False, "refine": True},
    "AR": {"name": "Arabic",     "rtl": True,  "refine": True},
    "FA": {"name": "Persian",    "rtl": True,  "refine": True},
    "HE": {"name": "Hebrew",     "rtl": True,  "refine": True},
    "UR": {"name": "Urdu",       "rtl": True,  "refine": True},
    "HI": {"name": "Hindi",      "rtl": False, "refine": False},
    "TR": {"name": "Turkish",    "rtl": False, "refine": False},
    "PL": {"name": "Polish",     "rtl": False, "refine": False},
    "NL": {"name": "Dutch",      "rtl": False, "refine": False},
}

def lang_display(code: str) -> str:
    info = LANGUAGES.get(code.upper())
    return f"{code.upper()} ({info['name']})" if info else code.upper()

def needs_refine(code: str) -> bool:
    return LANGUAGES.get(code.upper(), {}).get("refine", False)

def is_rtl(code: str) -> bool:
    return LANGUAGES.get(code.upper(), {}).get("rtl", False)