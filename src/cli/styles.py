import os
import sys

# prompt_toolkit cuantiza a 256 colores salvo que se le diga lo contrario, y rich pinta
# 24 bits: la misma constante salia con dos valores distintos en la misma pantalla
# (#5f6673 → #6c6c6c, #b3bac4 → #bcbcbc, #56a8ee → #5fafff). Medido capturando la
# terminal con un pty. Va aqui y no en main.py porque los modulos de UI tambien se
# ejecutan sueltos (python -m src.cli.folder_picker) y la lee al arrancar cada prompt.
os.environ.setdefault("PROMPT_TOOLKIT_COLOR_DEPTH", "DEPTH_24_BIT")

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
    igual. La columna de etiquetas se ajusta a la mas larga en vez de ir a un ancho
    fijo de 10: con "File" y "apuntes.md" el dato quedaba a seis espacios del nombre y
    dejaban de leerse como una pareja. El dato se recorta con puntos suspensivos antes
    que envolverse, porque una respuesta partida en dos lineas no se lee de un vistazo.
    """
    from rich.table import Table
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style=META, no_wrap=True)
    tabla.add_column(overflow="ellipsis", no_wrap=True)
    for etiqueta, valor in filas:
        tabla.add_row(etiqueta, valor)
    return tabla


def clear_screen():
    """Clear terminal screen synchronously through Python's stdout buffer."""
    sys.stdout.flush()
    sys.stdout.write('\033[H\033[2J\033[3J')
    sys.stdout.flush()

# ── Paleta ───────────────────────────────────────────────────────────────────
# Los cuatro grises eran en realidad dos: el resumen, las opciones y la pregunta
# compartian blanco (#d4d7dc / #d4d7dc / #e8e9ec), y por eso la pantalla se veia
# plana por mucho que la estructura estuviera bien. Aqui estan separados de verdad,
# con los mismos tonos y sin un color nuevo: cambian tres hexadecimales.
GREEN   = "#47d179"
BLUE    = "#56a8ee"
YELLOW  = "#f4b73d"
RED     = "#dc3b3b"
CYAN    = "#47d1d1"
MAGENTA = "#b770db"
DIM     = "#5f6673"
MUTED   = "#868e9c"
FG      = "#b3bac4"
BRIGHT  = "#ffffff"

# ── La paleta del picker ─────────────────────────────────────────────────────
# El wizard, la confirmacion y el selector de carpetas son la misma pantalla: una
# cabecera, una pregunta y una lista. Ahi cada color tiene un unico rol y ninguno se
# repite entre dos niveles, que era el problema de verdad — no que hubiera pocos
# colores, sino que el mismo gris hacia de etiqueta, de opcion descartada y de dato.
#
#   BRAND    solo "mdtranslator"
#   TITLE    solo el titulo de la pregunta viva
#   SELECT   solo el item bajo el cursor (y el ❯ que lo senala)
#   CONTEXT  las migas y los datos ya contestados
#   OPTION   todo lo no elegido
#   META     version, subtitulos, pistas de teclado, "back"
#   RULE     el filete que cierra el titulo, y nada mas
#
# La rampa de grises va de menos a mas: META < CONTEXT < OPTION < TITLE. Los cuatro
# pesos se distinguen; antes eran tres tonos casi iguales entre #d4d7dc y #e8e9ec.
BRAND   = "#7dcfff"
TITLE   = "#e6e6e6"
SELECT  = "#7aa2f7"
CONTEXT = "#565f89"
OPTION  = "#6b7280"
META    = "#4b5263"
RULE    = "#33364a"

# questionary abre cada opcion con " ❯ ", asi que el puntero cae en la columna 1. Lo
# que pinta rich por su cuenta —la marca, las migas, el titulo, el filete— lleva este
# margen para caer en esa misma columna y no un caracter a la izquierda.
MARGEN  = " "

VERSION = "2.1.0"


def aire_superior() -> int:
    """Lineas en blanco por encima de la marca. API: entero, entre 1 y 4.

    Con una fija, la cabecera quedaba clavada al borde de arriba —y a pantalla
    completa se nota el doble, porque debajo del bloque queda media ventana vacia y lo
    que se lee es que la pantalla se ha quedado corta—. Depende solo del alto de la
    ventana y no de lo que haya en ella: si dependiera del contenido, el bloque saltaria
    de sitio entre una pregunta y la siguiente.

    En una ventana corta se queda en una linea: la pantalla mas alta —los dieciocho
    idiomas— ya va justa de sitio, y gastar renglones arriba es empujarla fuera.
    """
    return max(1, min(4, (console.height - 20) // 8))


def marca() -> "Text":
    """La linea de marca, identica en todas las pantallas de pregunta.

    Va aqui y no en cada vista porque es lo unico que no cambia nunca: si el wizard y
    la confirmacion la escriben cada uno por su cuenta, acaban con dos azules.
    """
    from rich.text import Text
    # El estilo base de un Text lo heredan los tramos que se le anaden: puesto en el
    # constructor, la version salia tambien en negrita.
    t = Text(MARGEN)
    t.append("mdtranslator", style=f"bold {BRAND}")
    t.append(f" v{VERSION}", style=META)
    return t


def mezcla(a: str, b: str, t: float) -> str:
    """Interpola dos colores '#rrggbb'. API: hex. Unico sitio donde se mezcla color."""
    t = max(0.0, min(1.0, t))
    ca = (int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16))
    cb = (int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


# ── La barra de progreso ─────────────────────────────────────────────────────
# Lo hecho lo pinta el fondo de las celdas, no un glifo repetido, asi que hay que
# fijar contra que fondo se mezclan los tonos: se da por hecho un terminal oscuro.
# Lo que queda no se pinta, se dibuja con un filete en la base. Pintarlo tambien de
# fondo parecia lo coherente y quedaba mal: en un terminal no hay separacion entre
# renglones, asi que los cinco railes se fundian en un unico rectangulo oscuro de
# 22x5 con un borde duro a la derecha — mas peso en pantalla, no menos, que era
# justo lo contrario de lo que se buscaba.
TERM_BG  = "#292929"
# Gris y no azul: aqui el azul significa "donde esta el cursor" y una barra no es un
# cursor. Ademas la barra ocupa 22 de las 48 columnas de su fila y se repite en cada
# una; pintada de un color con significado, se lleva por delante el primer ✓ verde,
# que es lo unico de la pantalla que de verdad responde a algo.
BAR_TINT = "#aab1bc"       # la cabeza: el frente de lo que avanza
BAR_BODY = mezcla(TERM_BG, BAR_TINT, 0.70)   # lo ya hecho
BAR_RAIL = mezcla(TERM_BG, BAR_TINT, 0.25)   # lo que queda, y la fila ya terminada

# ── Un color, un significado ─────────────────────────────────────────────────
# El verde marcaba dos cosas a la vez: la opcion elegida en el wizard y el exito de
# una tarea. Con cuatro preguntas contestadas la pantalla llegaba verde al pipeline
# y el primer ✓ de verdad ya no destacaba de nada. Reparto actual, que es el de
# git status / npm install / docker build:
#
#   DIM     lo que nombra o esta en cola: etiquetas, unidades
#   MUTED   dato secundario
#   FG      contenido normal
#   BRIGHT  contenido que responde a la pregunta de la pantalla
#   CYAN    identidad de idioma, y nada mas
#   BLUE    donde esta el cursor, y a donde lleva un enlace
#   YELLOW  en marcha o aviso
#   GREEN   exito, y nada mas
#   RED     fallo
#   BAR_*   la barra de progreso, en gris: no dice nada, solo dice "sigo vivo"
#
# Si anades un color, dile aqui que significa antes de usarlo en una vista.
#
# Este reparto es el de las vistas de ejecucion (pipeline y resultados), donde lo que
# hay que leer es el estado de cada tarea. Las pantallas de pregunta usan la paleta
# del picker de mas arriba: alli no hay estados, hay niveles. El cian no cruza — en el
# picker la identidad de idioma es un dato mas y va en CONTEXT, porque BRAND ya ocupa
# esa zona del espectro y dos cianes en la misma pantalla dejan de significar cosas
# distintas.

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
#
# `separator` es la unica clase que questionary tiene para todo lo que no es una
# opcion, asi que aqui vale para los subtitulos y para las lineas en blanco que
# separan bloques. El filete NO es un separator: lo pinta rich antes de arrancar el
# prompt, porque va en otro color y compartiendo clase saldrian los dos iguales.
WIZARD_STYLE = questionary.Style([
    ("qmark",       ""),                      # sin simbolo delante de la pregunta
    ("question",    f"fg:{TITLE} bold"),
    ("answer",      f"fg:{SELECT} bold"),
    ("pointer",     f"fg:{SELECT} bold"),     # ❯ — donde estas
    ("highlighted", f"fg:{SELECT} bold"),     # la opcion bajo el cursor
    # noreverse a proposito: prompt_toolkit pinta "selected" en video inverso y la
    # multiseleccion salia con bloques de fondo. Mismo color que el cursor porque es
    # el mismo rol —lo elegido—; lo que separa "marcado" de "donde estoy" es la
    # negrita del cursor y el ❯, no un segundo color.
    ("selected",    f"fg:{SELECT} noreverse"),  # marcada en un checkbox
    ("instruction", f"fg:{META}"),
    ("separator",   f"fg:{META} italic"),     # subtitulo de una opcion
    ("text",        f"fg:{OPTION}"),          # lo no elegido
    ("disabled",    f"fg:{META} italic"),
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
