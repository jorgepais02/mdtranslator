import sys
import questionary
from rich.console import Console

console = Console()

def elide(texto: str, cabe: int) -> str:
    """Recorta por el final dejando puntos suspensivos. Nunca devuelve mas de `cabe`."""
    if cabe <= 1:
        return texto[:max(0, cabe)]
    return texto if len(texto) <= cabe else texto[:cabe - 1] + "…"


def summary_grid(filas) -> "Table":
    """Bloque etiqueta/dato: gris a la izquierda, contenido a la derecha.

    Lo usan el wizard y la confirmacion, que ensenan lo mismo y tienen que verse
    igual. Etiqueta a ancho fijo para que los datos queden en columna; el dato se
    recorta con puntos suspensivos antes que envolverse, porque una respuesta partida
    en dos lineas deja de leerse de un vistazo.
    """
    from rich.table import Table
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style=DIM, width=10, no_wrap=True)
    tabla.add_column(overflow="ellipsis", no_wrap=True)
    for etiqueta, valor in filas:
        tabla.add_row(etiqueta, valor)
    return tabla


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

# ── Un color, un significado ─────────────────────────────────────────────────
# El verde marcaba dos cosas a la vez: la opcion elegida en el wizard y el exito de
# una tarea. Con cuatro preguntas contestadas la pantalla llegaba verde al pipeline
# y el primer ✓ de verdad ya no destacaba de nada. Reparto actual, que es el de
# git status / npm install / docker build:
#
#   DIM     lo que nombra o esta en cola: etiquetas, unidades, opciones descartadas
#   FG      contenido normal
#   BRIGHT  contenido que responde a la pregunta de la pantalla
#   CYAN    identidad de idioma, y nada mas
#   BLUE    donde esta el cursor / lo que avanza
#   YELLOW  en marcha o aviso
#   GREEN   exito, y nada mas
#   RED     fallo
#
# Si anades un color, dile aqui que significa antes de usarlo en una vista.

STATUS_QUEUED = "queued"

def status_style(status: str) -> str:
    """Color de un estado de tarea. Unico sitio donde se decide. API: estilo rich."""
    if status.startswith("✓"):
        return GREEN
    if status.startswith("✗"):
        return RED
    if status in (STATUS_QUEUED, "waiting", ""):
        return DIM
    return YELLOW

# ── questionary style ─────────────────────────────────────────────────────────
# El puntero va en azul, no en verde: marca donde esta el cursor, no un acierto.
WIZARD_STYLE = questionary.Style([
    ("qmark",       ""),                     # sin simbolo delante de la pregunta
    ("question",    f"fg:{BRIGHT} bold"),
    ("answer",      f"fg:{BRIGHT} bold"),
    ("pointer",     f"fg:{BLUE} bold"),      # ❯ — donde estas
    ("highlighted", f"fg:{BRIGHT} bold"),    # la opcion bajo el cursor
    # noreverse a proposito: prompt_toolkit pinta "selected" en video inverso y la
    # multiseleccion salia con bloques cian de fondo. El circulo ya dice que esta
    # marcada; el cian solo tiene que decir "esto es un idioma".
    ("selected",    f"fg:{CYAN} noreverse"),  # marcada en un checkbox
    ("instruction", f"fg:{DIM}"),
    ("separator",   f"fg:{DIM}"),
    ("text",        f"fg:{FG}"),
    ("disabled",    f"fg:{DIM} italic"),
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
