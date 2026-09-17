"""
Refinamiento nodo a nodo de MD traducido con Gemini.

Estrategia:
  - Parsear el MD en nodos tipados
  - Mandar a Gemini SOLO texto plano (paragraph, list_item, blockquote)
  - Los inline spans se extraen como placeholders antes de Gemini
  - El MD de salida es estructuralmente idéntico al de entrada

Nodos refinables:  paragraph, list_item, blockquote
Nodos intocables:  heading, code_block, table, hr, blank, frontmatter

API:
    refine_markdown(lines, lang_code, cache=None, cancelado=None) -> (lineas, aviso)
CLI:
    python -m src.document.refiner input.md lang_code
"""

import os, re, time
from dataclasses import dataclass
from typing import Literal
from google import genai
from google.genai import types
from rich.console import Console

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
        li = re.match(r'^(\s*(?:[-*+]|\d+\.)\s)(.*)', line)
        if li:
            nodes.append(Node("list_item", line, li.group(2), li.group(1)))
            continue
        nodes.append(Node("paragraph", line, line, ""))

    return nodes


INLINE_RE = re.compile(
    r'(`[^`]+`'
    r'|\*{1,3}[^*\n]+\*{1,3}'
    r'|_{1,3}[^_\n]+_{1,3}'
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
    "You receive numbered plain-text lines from auto-translated academic notes. "
    "Humanize and naturalize each line so it sounds completely fluent. "
    "Rules: return ONLY the numbered lines — same count, same order. "
    "Preserve placeholders like ⟦0⟧ ⟦1⟧ exactly. "
    "Do not change proper nouns, acronyms, or technical terms. "
    "If a line is already natural, return it unchanged."
)

BATCH = 25

# La caché de refinamiento comparte tabla con la de traducción: su clave es
# (texto, idioma, proveedor), así que el proveedor hace de namespace. Lo que Gemini
# ya refinó no se vuelve a pagar, y por eso relanzar un lote que murió a la mitad
# solo repite lo que falta.
CACHE_PROVIDER = "gemini-refine"

# Cuando salta el 429, el propio error dice cuánto falta para que se libere hueco
# (`retryDelay`), y ese número baja en cada intento: medido, 59s → 34s → 9s. Esperar
# lo que pide y reintentar recupera la petición; rendirse al primer 429 deja el
# documento sin refinar teniendo la cuota a un minuto de distancia.
_RETRY_DELAY_RE = re.compile(r"'retryDelay':\s*'(\d+)s'")
_MAX_INTENTOS   = 2
_MAX_ESPERA     = 60          # s: por encima de esto, mejor avisar que colgar el lote
_PASO_ESPERA    = 1           # s: se duerme a trocitos para poder atender un Ctrl+C


def _espera_pedida(error: Exception) -> int | None:
    """Los segundos que pide un 429, o None si el error es de otra cosa."""
    texto = str(error)
    if "429" not in texto and "RESOURCE_EXHAUSTED" not in texto:
        return None
    m = _RETRY_DELAY_RE.search(texto)
    return min(int(m.group(1)) + 1, _MAX_ESPERA) if m else _MAX_ESPERA


def es_aviso_de_cuota(aviso: str | None) -> bool:
    """True si el aviso viene de la cuota de Gemini y no de otro fallo. API: bool.

    Lo usa el pipeline para dejar de intentarlo en el resto de la ejecución: un 503 o
    una respuesta con líneas de más son cosa de ese documento, pero la cuota es de
    todos, y probar uno por uno cuesta un minuto de espera por documento.
    """
    if not aviso:
        return False
    t = str(aviso).lower()
    return "429" in t or "resource_exhausted" in t


def _dormir(segundos: int, cancelado) -> bool:
    """Duerme a trocitos. False si hay que abandonar porque el usuario canceló."""
    for _ in range(segundos):
        if cancelado is not None and cancelado():
            return False
        time.sleep(_PASO_ESPERA)
    return True

def _call_gemini(texts: list[str], lang: str, client, cancelado=None) -> tuple[list[str], str | None]:
    if not texts:
        return [], None
    ultimo: Exception | None = None
    for intento in range(_MAX_INTENTOS):
        try:
            return _una_llamada(texts, lang, client)
        except Exception as e:
            espera = _espera_pedida(e)
            if espera is None or intento == _MAX_INTENTOS - 1:
                raise
            ultimo = e
            if not _dormir(espera, cancelado):
                raise
    raise ultimo          # inalcanzable, pero deja claro que aquí no se devuelve None


def _una_llamada(texts: list[str], lang: str, client) -> tuple[list[str], str | None]:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Refine these {len(texts)} lines:\n\n{numbered}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM.format(lang=lang.upper()),
            temperature=0.2,
        ),
    )
    raw = resp.text or ""
    out = []
    for line in raw.strip().splitlines():
        m = re.match(r'^\d+\.\s+(.*)', line)
        if m:
            out.append(m.group(1))
    if len(out) != len(texts):
        return texts, f"Gemini returned {len(out)}/{len(texts)} lines"
    return out, None


REFINABLE = {"paragraph", "list_item", "blockquote"}


def _refinar(textos: list[str], lang_code: str, client, cache, cancelado):
    """Los textos refinados en el mismo orden, o (None, aviso).

    Lo que ya está en caché no viaja, y las líneas repetidas dentro del documento
    cuentan una sola vez: en unos apuntes, "Fuente: INCIBE" sale veinte veces.
    """
    hechos: dict[str, str] = {}
    if cache is not None:
        for t in dict.fromkeys(textos):
            guardado = cache.get(t, lang_code, CACHE_PROVIDER)
            if guardado is not None:
                hechos[t] = guardado

    faltan = [t for t in dict.fromkeys(textos) if t not in hechos]
    for start in range(0, len(faltan), BATCH):
        lote = faltan[start:start + BATCH]
        salida, aviso = _call_gemini(lote, lang_code, client, cancelado)
        if aviso:
            return None, aviso
        if cache is not None:
            cache.set_many(list(zip(lote, salida)), lang_code, CACHE_PROVIDER)
        hechos.update(zip(lote, salida))

    return [hechos[t] for t in textos], None


def refine_markdown(lines: list[str], lang_code: str, cache=None,
                    cancelado=None) -> tuple[list[str], str | None]:
    """Refina un MD traducido. Devuelve (líneas, warning_o_None) sin imprimir nada.

    cache     — cualquier objeto con get(texto, lang, proveedor) y set_many(pares, …);
                sin él el refinamiento funciona igual, pero se paga cada vez
    cancelado — callable que dice si hay que abandonar mientras se espera un 429
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return lines, "GEMINI_API_KEY not set"
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return lines, f"Gemini init failed: {e}"

    nodes = parse_nodes(lines)
    idxs, texts, imaps = [], [], []
    for i, n in enumerate(nodes):
        if n.type in REFINABLE and n.text.strip():
            clean, tok = extract_inline(n.text)
            idxs.append(i)
            texts.append(clean)
            imaps.append(tok)

    try:
        refined, warn = _refinar(texts, lang_code, client, cache, cancelado)
        if warn:
            return lines, warn
    except Exception as e:
        # Con el mensaje pelado, un 503 de Gemini llegaba a la tabla final como
        # "Google Drive server error": el aviso tiene que decir de donde viene.
        return lines, f"Gemini: {e}"

    for pos, idx in enumerate(idxs):
        n = nodes[idx]
        restored = restore_inline(refined[pos], imaps[pos])
        nodes[idx] = Node(n.type, n.prefix + restored, restored, n.prefix)

    return [n.raw for n in nodes], None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m src.document.refiner input.md lang_code")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        lines = f.read().splitlines()
    result, warning = refine_markdown(lines, sys.argv[2])
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)
    print("\n".join(result))
