"""
Refinamiento nodo a nodo de MD traducido con un modelo de IA (ver src/ai/).

Estrategia:
  - Parsear el MD en nodos tipados
  - Mandar al modelo SOLO texto plano (paragraph, list_item, blockquote)
  - Los inline spans se extraen como placeholders antes de la llamada
  - El MD de salida es estructuralmente idéntico al de entrada

Nodos refinables:  paragraph, list_item, blockquote
Nodos intocables:  heading, code_block, table, hr, blank, frontmatter

API:
    refine_markdown(lines, lang_code, cache=None, cancelado=None)
        -> (lineas, aviso, cambio_de_modelo)
CLI:
    python -m src.document.refiner input.md lang_code
"""

import re, time
from dataclasses import dataclass
from typing import Literal
from rich.console import Console

# Dos formas de llegar aqui: importado por la CLI (con src/ en sys.path) o ejecutado
# con python -m src.document.refiner. El relativo solo vale en el segundo caso.
try:
    from ..ai.base import (MAX_ESPERA, MAX_INTENTOS, PISTAS_CUOTA, AIError,
                           cambio_de_modelo, espera_pedida)
    from ..ai.registry import get_model
    from ..core.parser import LETRA_DE_LISTA
except ImportError:
    from ai.base import (MAX_ESPERA, MAX_INTENTOS, PISTAS_CUOTA, AIError,
                         cambio_de_modelo, espera_pedida)
    from ai.registry import get_model
    from core.parser import LETRA_DE_LISTA

console = Console(stderr=True)

NodeType = Literal[
    "frontmatter", "heading", "paragraph", "list_item",
    "blockquote", "code_block", "table_row", "hr", "blank"
]

@dataclass
class Node:
    type:   NodeType
    raw:    str
    text:   str
    prefix: str


def split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[:i + 1], lines[i + 1:]
    return [], lines


def parse_nodes(lines: list[str]) -> list[Node]:
    nodes = []
    fm_lines, body = split_frontmatter(lines)

    for l in fm_lines:
        nodes.append(Node("frontmatter", l, "", ""))

    in_code = False
    fence   = ""
    for line in body:
        m = re.match(r'^(`{3,}|~{3,})', line)
        if m:
            if not in_code:
                in_code, fence = True, m.group(1)
            elif line.strip().startswith(fence):
                in_code, fence = False, ""
            nodes.append(Node("code_block", line, "", ""))
            continue
        if in_code:
            nodes.append(Node("code_block", line, "", ""))
            continue
        if not line.strip():
            nodes.append(Node("blank", line, "", ""))
            continue
        if re.match(r'^[-*_]{3,}\s*$', line):
            nodes.append(Node("hr", line, "", ""))
            continue
        if re.match(r'^#{1,6}\s', line):
            nodes.append(Node("heading", line, "", ""))
            continue
        if re.match(r'^\s*\|', line) or re.match(r'^[\s|:-]+$', line):
            nodes.append(Node("table_row", line, "", ""))
            continue
        bq = re.match(r'^(>\s?)(.*)', line)
        if bq:
            nodes.append(Node("blockquote", line, bq.group(2), bq.group(1)))
            continue
        li = re.match(rf'^(\s*(?:[-*+]|\d+\.|{LETRA_DE_LISTA})\s)(.*)', line)
        if li:
            nodes.append(Node("list_item", line, li.group(2), li.group(1)))
            continue
        nodes.append(Node("paragraph", line, line, ""))

    return nodes


# El span con atributos ("[C]{.notranslate}") va antes que el enlace: con el enlace
# primero, su ".*?" se estira desde el "[" del span hasta el "](" del siguiente enlace de
# la línea y se lleva por delante todo lo de en medio.
INLINE_RE = re.compile(
    r'(`[^`]+`'
    r'|\*{1,3}[^*\n]+\*{1,3}'
    r'|_{1,3}[^_\n]+_{1,3}'
    r'|\[[^\]\n]*\]\{[^}\n]*\}'
    r'|\[.*?\]\(.*?\)'
    r')'
)

def extract_inline(text: str) -> tuple[str, dict]:
    tokens = {}
    def sub(m):
        k = f"⟦{len(tokens)}⟧"
        tokens[k] = m.group(0)
        return k
    return INLINE_RE.sub(sub, text), tokens

def restore_inline(text: str, tokens: dict) -> str:
    for k, v in tokens.items():
        text = text.replace(k, v)
    return text


SYSTEM = (
    "You are a native-speaker editor for {lang}. "
    "You receive numbered plain-text lines in {lang} from auto-translated academic notes. "
    "Humanize and naturalize each line so it sounds completely fluent. "
    "Rules: return ONLY the numbered lines — same count, same order. "
    "Every line stays in {lang}: never translate a line into another language. "
    "Preserve placeholders like ⟦0⟧ ⟦1⟧ exactly. "
    "Do not change proper nouns, acronyms, or technical terms. "
    "If a line is already natural, return it unchanged."
)

# El idioma va por su nombre y no por el código: con "editor for AR" y el contexto del
# documento —que está en el idioma de origen— pegado detrás, un lote de líneas cortas de
# un documento árabe del módulo 19 volvió entero en español, y reescrito ("Integridad"
# pasó a "Seguridad"). Todos los idiomas que se refinan (styles.needs_refine) tienen
# alfabeto propio, y con él se comprueba que lo que vuelve sigue en su idioma. Uno que
# falte aquí se refina igual, con el código en el prompt y sin esa comprobación.
_ESCRITURA = {
    "ar": ("Arabic",   "؀-ۿ"),
    "fa": ("Persian",  "؀-ۿ"),
    "ur": ("Urdu",     "؀-ۿ"),
    "he": ("Hebrew",   "֐-׿"),
    "zh": ("Chinese",  "一-鿿"),
    "ja": ("Japanese", "぀-ヿ一-鿿"),
    "ko": ("Korean",   "가-힯"),
}


def _escritura(lang_code: str) -> tuple[str, str | None]:
    return _ESCRITURA.get(lang_code.split("-")[0].lower(), (lang_code.upper(), None))


def _en_su_idioma(original: str, refinado: str, lang_code: str) -> bool:
    """False si el modelo devolvió en otro idioma una línea que estaba en el suyo.

    Solo se puede decir de una línea que usaba el alfabeto del idioma: la que era
    "SHA-256" o un nombre de producto no tiene nada que comprobar.
    """
    letras = _escritura(lang_code)[1]
    if not letras:
        return True
    alfabeto = re.compile(f"[{letras}]")
    return not alfabeto.search(original) or bool(alfabeto.search(refinado))

# De que van los apuntes, pegado al SYSTEM. Es la red de seguridad de los idiomas que
# refinan: DeepL tiene su parametro `context` y Gemini lo mete en su prompt, pero **Azure
# no tiene nada equivalente** (su `category` es un modelo entrenado aparte y su diccionario
# dinamico, dice Microsoft, "solo es seguro para nombres propios"). Aqui se corrige venga
# de donde venga la traduccion, y sin una peticion de mas.
CONTEXTO = (" These notes are about: {contexto} "
            "Use that to pick the right sense of ambiguous terms and to keep the same "
            "term for the same concept throughout.")

BATCH = 25

# La caché de refinamiento comparte tabla con la de traducción: su clave es
# (texto, idioma, proveedor), así que el proveedor hace de namespace. Lo que ya se
# refinó no se vuelve a pagar, y por eso relanzar un lote que murió a la mitad solo
# repite lo que falta.
#
# El namespace sigue siendo "gemini-refine" aunque hoy pueda refinar cualquier modelo,
# y **no** lleva el id del modelo: metérselo invalidaría todo lo refinado hasta ahora
# (~23s por documento otra vez), por el mismo motivo por el que la clave de traducción
# no lleva source_lang. A cambio, un texto refinado por Cerebras se reutiliza aunque
# mañana el preferido sea Gemini — es un texto ya editado, no una traducción cruda.
CACHE_PROVIDER = "gemini-refine"

# Cuando salta el 429, el propio error dice cuánto falta para que se libere hueco
# (`retryDelay`), y ese número baja en cada intento: medido, 59s → 34s → 9s. Esperar
# lo que pide y reintentar recupera la petición; rendirse al primer 429 deja el
# documento sin refinar teniendo la cuota a un minuto de distancia. La lectura de ese
# número vive en ai/base.py, porque cada API lo cuenta a su manera.
_MAX_INTENTOS = MAX_INTENTOS
_MAX_ESPERA   = MAX_ESPERA
_PASO_ESPERA  = 1             # s: se duerme a trocitos para poder atender un Ctrl+C


# El aviso de las tareas que se saltan el refinado porque ya no queda cuota. Es el
# mismo texto que trae el fallo de verdad —y vive aqui, no en el pipeline, porque el
# vocabulario de estos avisos es de este modulo—: si dijeran cosas distintas, la
# pantalla final contaria dos historias del mismo motivo y no colapsarian en una linea.
AVISO_SIN_CUOTA = ("429 RESOURCE_EXHAUSTED — no quota left on any model, "
                   "refining skipped")


def es_aviso_de_cuota(aviso: str | None) -> bool:
    """True si el aviso viene de la cuota de Gemini y no de otro fallo. API: bool.

    Lo usa el pipeline para dejar de intentarlo en el resto de la ejecución: un 503 o
    una respuesta con líneas de más son cosa de ese documento, pero la cuota es de
    todos, y probar uno por uno cuesta un minuto de espera por documento.
    """
    if not aviso:
        return False
    t = str(aviso).lower()
    return any(pista in t for pista in PISTAS_CUOTA)


def _dormir(segundos: int, cancelado) -> bool:
    """Duerme a trocitos. False si hay que abandonar porque el usuario canceló."""
    for _ in range(segundos):
        if cancelado is not None and cancelado():
            return False
        time.sleep(_PASO_ESPERA)
    return True

def _llamar_modelo(texts: list[str], lang: str, modelo, cancelado=None,
                   contexto: str | None = None) -> tuple[list[str], str | None]:
    """Un lote refinado, reintentando si lo que falla es la cuota.

    El orden importa: con varios modelos configurados, la lista entera se prueba
    **sin dormir** (lo hace FallbackModel) y solo se llega a esta espera cuando
    ninguno tiene cuota. Al reves —esperar 60s con el primero antes de probar el
    segundo— eran hasta 120s por lote para acabar usando uno que estaba libre.
    """
    if not texts:
        return [], None
    ultimo: Exception | None = None
    for intento in range(_MAX_INTENTOS):
        try:
            return _una_llamada(texts, lang, modelo, contexto)
        except Exception as e:
            espera = espera_pedida(e)
            if espera is None or intento == _MAX_INTENTOS - 1:
                raise
            ultimo = e
            if not _dormir(espera, cancelado):
                raise
    raise ultimo          # inalcanzable, pero deja claro que aquí no se devuelve None


def _una_llamada(texts: list[str], lang: str, modelo,
                 contexto: str | None = None) -> tuple[list[str], str | None]:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    system = SYSTEM.format(lang=_escritura(lang)[0])
    if contexto:
        system += CONTEXTO.format(contexto=contexto)
    raw = modelo.complete(
        f"Refine these {len(texts)} lines:\n\n{numbered}",
        system=system,
        temperature=0.2,
    )
    out = []
    for line in raw.strip().splitlines():
        m = re.match(r'^\d+\.\s+(.*)', line)
        if m:
            # rstrip: dos espacios al final de una linea son un salto forzado en
            # Markdown, y Pandoc los convierte en un <br> dentro del parrafo. Gemini
            # no los ponia; openai/gpt-oss-120b cierra con ellos casi cada linea.
            out.append(m.group(1).rstrip())
    if len(out) != len(texts):
        return texts, f"{modelo.ref} returned {len(out)}/{len(texts)} lines"
    return out, None


REFINABLE = {"paragraph", "list_item", "blockquote"}


def _refinar(textos: list[str], lang_code: str, modelo, cache, cancelado,
             contexto: str | None = None):
    """Los textos refinados en el mismo orden, o (None, aviso).

    Lo que ya está en caché no viaja, y las líneas repetidas dentro del documento
    cuentan una sola vez: en unos apuntes, "Fuente: INCIBE" sale veinte veces.
    """
    hechos: dict[str, str] = {}
    if cache is not None:
        for t in dict.fromkeys(textos):
            guardado = cache.get(t, lang_code, CACHE_PROVIDER)
            # Lo que se guardó antes de mirar el idioma puede estar en otro: se vuelve a
            # pedir, y la respuesta buena lo sustituye.
            if guardado is not None and _en_su_idioma(t, guardado, lang_code):
                hechos[t] = guardado

    faltan = [t for t in dict.fromkeys(textos) if t not in hechos]
    for start in range(0, len(faltan), BATCH):
        lote = faltan[start:start + BATCH]
        salida, aviso = _llamar_modelo(lote, lang_code, modelo, cancelado, contexto)
        if aviso:
            return None, aviso
        # Una línea que vuelve en otro idioma se queda con la traducción cruda, que es
        # la regla de las marcas rotas: refinar nunca deja el documento peor. Y no se
        # guarda, para que la próxima pasada lo intente otra vez.
        buenas = {t: s for t, s in zip(lote, salida) if _en_su_idioma(t, s, lang_code)}
        if cache is not None:
            cache.set_many(list(buenas.items()), lang_code, CACHE_PROVIDER)
        hechos.update({t: buenas.get(t, t) for t in lote})

    return [hechos[t] for t in textos], None


def refine_markdown(lines: list[str], lang_code: str, cache=None,
                    cancelado=None,
                    contexto: str | None = None) -> tuple[list[str], str | None, dict | None]:
    """Refina un MD traducido. Devuelve (líneas, warning_o_None, cambio_de_modelo).

    cache     — cualquier objeto con get(texto, lang, proveedor) y set_many(pares, …);
                sin él el refinamiento funciona igual, pero se paga cada vez
    cancelado — callable que dice si hay que abandonar mientras se espera un 429
    contexto  — de qué van los apuntes, para desambiguar. No cambia la clave de la
                caché: lo ya refinado se reutiliza tal cual y solo lo nuevo lo lleva

    El tercer valor solo trae algo cuando **no** contestó el modelo preferido: si el
    resultado sale del primero de la lista no hay nada que contar, y la pantalla final
    únicamente habla del modelo cuando cambió.
    """
    try:
        modelo = get_model()
    except AIError as e:
        return lines, str(e), None

    nodes = parse_nodes(lines)
    idxs, texts, imaps = [], [], []
    for i, n in enumerate(nodes):
        if n.type in REFINABLE and n.text.strip():
            clean, tok = extract_inline(n.text)
            idxs.append(i)
            texts.append(clean)
            imaps.append(tok)

    try:
        refined, warn = _refinar(texts, lang_code, modelo, cache, cancelado, contexto)
        if warn:
            return lines, warn, cambio_de_modelo(modelo)
    except Exception as e:
        # Con el mensaje pelado, un 503 de Gemini llegaba a la tabla final como
        # "Google Drive server error": el aviso tiene que decir de donde viene. Los
        # modelos lo traen delante (proveedor:modelo), asi que ya no hace falta
        # anadirselo aqui.
        return lines, str(e) if isinstance(e, AIError) else f"Gemini: {e}", None

    for pos, idx in enumerate(idxs):
        n = nodes[idx]
        restored = restore_inline(refined[pos], imaps[pos])
        # Las llaves son por línea, pero el modelo edita el lote entero: mueve una marca
        # a la línea de al lado, o la parte por dentro ("⟦0 lock⟧"). La vecina se queda
        # sin nada que restaurar y el símbolo llega al documento; la de origen pierde su
        # cursiva y, con ella, la palabra. Pasó en el módulo 19, en dos apuntes chinos.
        # Esa línea se queda sin refinar a propósito: la traducción cruda se lee, "⟦0⟧"
        # no, y refinar nunca puede dejar el documento peor de lo que estaba.
        if any(k not in refined[pos] for k in imaps[pos]) or "⟦" in restored or "⟧" in restored:
            continue
        nodes[idx] = Node(n.type, n.prefix + restored, restored, n.prefix)

    return [n.raw for n in nodes], None, cambio_de_modelo(modelo)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)
    if len(sys.argv) < 3:
        print("Usage: python -m src.document.refiner input.md lang_code")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        lines = f.read().splitlines()
    result, warning, cambio = refine_markdown(lines, sys.argv[2])
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)
    if cambio:
        print(f"⚠ refined with {cambio['used']} — {cambio['instead_of']} "
              f"had {cambio['reason']}", file=sys.stderr)
    print("\n".join(result))
