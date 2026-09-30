"""
Convierte texto raw en MD académico con Gemini.

API:
    generate_markdown(text: str, lang: str = "es", title: str | None = None) -> str

CLI:
    python -m src.integrations.generate_md input.txt [-o output.md] [--lang es]
"""

import argparse, re, sys
from pathlib import Path

# Dos formas de llegar aqui: importado por la CLI (con src/ en sys.path) o ejecutado
# con python -m src.integrations.generate_md. El relativo solo vale en el segundo caso.
from langdetect import detect_langs, DetectorFactory
DetectorFactory.seed = 0

try:
    from ..ai.base import AIError
    from ..ai.registry import get_model
    from ..core.parser import conserva_la_parte
except ImportError:
    from ai.base import AIError
    from ai.registry import get_model
    from core.parser import conserva_la_parte

SYSTEM = """You are an academic note-taking assistant.
Convert raw transcriptions into clean, structured Markdown notes.

Rules:
- Use # for title, ## for sections, ### for subsections
- Prefer paragraphs over lists — use lists only when content is genuinely enumerable
- Lists use only "- " (never asterisks)
- Crucial: You MUST leave an empty blank line before and after ANY list
- Ordered steps use "1. 2. 3."
- Never fake headings with **bold** inside lists
- Each heading must be followed by at least one paragraph before any list
- Each heading must stand on its own: someone reading only the headings must know
  what each one refers to. Never a bare ambiguous noun — write "Source data
  selection", not "Selection of Origin". A heading is translated as an isolated
  string, so what it leaves out cannot be recovered from the paragraph below
- Remove greetings, author names, URLs, chapter numbers from titles
- When the source filename is given and ends with a part indicator like (I), (II) or
  (III), the title MUST end with that same indicator, parentheses included
- No decorative separators (---)
- Technical, neutral, academic tone
- Write in the language of the transcription. Never translate it
- Format, do not summarize: keep every tool, product, proper name, figure and example
  from the transcription. "Mimikatz" stays "Mimikatz", never "specialized software"
- Return ONLY the Markdown content"""

INVALID_RE = re.compile(r'(<[a-z]+[\s>]|\$\$|^\* )', re.MULTILINE)

# "3. Jaulas de Faraday (II)" -> el numero es la posicion en el modulo, no parte del
# titulo; SYSTEM ya pide quitarlo, pero el que le pasamos como contexto va limpio.
_PREFIJO_NUM_RE = re.compile(r"^\s*\d+\s*[.)-]\s*")

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    # Y sin espacios al final de linea: en Markdown dos espacios son un salto forzado
    # y Pandoc los mete como <br> en medio del parrafo. Ver refiner._una_llamada, que
    # es donde se vio: openai/gpt-oss-120b cierra con ellos casi cada linea.
    return "\n".join(l.rstrip() for l in text.strip().splitlines())

# El idioma se nombra y luego se comprueba. En el módulo 20, cuatro de seis
# transcripciones españolas volvieron formateadas en inglés: con `lang="es"` el prompt
# no decía nada del idioma, y todo lo que el modelo veía aparte de la transcripción
# —SYSTEM y sus ejemplos de encabezados— estaba en inglés. Es el mismo fallo que el
# refiner (_ESCRITURA), aquí un paso antes, y con un agravante: el .md se guarda al
# lado del .txt y gana sobre él en las siguientes ejecuciones.
_NOMBRES = {"es": "Spanish", "en": "English", "fr": "French", "pt": "Portuguese",
            "it": "Italian", "de": "German", "ca": "Catalan"}

# Por debajo no se afirma nada: langdetect duda en textos cortos o muy mezclados, y un
# falso "está en otro idioma" tiraría un formateo bueno.
_CONFIANZA = 0.90
_MUESTRA   = 200


def _idioma(texto: str) -> str | None:
    """Código del idioma de un texto, o None si langdetect no está seguro."""
    if len(texto.strip()) < _MUESTRA:
        return None
    try:
        mejor = detect_langs(texto[:3000])[0]
    except Exception:
        return None
    return mejor.lang if mejor.prob >= _CONFIANZA else None


# Formatear no es resumir. En el mismo módulo 20, tres apuntes volvieron al 59–72 % de su
# transcripción y sin casi ningún nombre: «Dr. Ryuk (II)» es una lista de herramientas
# por fase del ataque y llegó con 1 de sus 9 (adfind, Mimikatz, ntds.dit, PsExec… eran
# «utilidades de consulta» y «software especializado»). La longitud no lo delata —hay
# apuntes buenos del M19 al 59 %—, pero los términos sí: en el M19 ninguno baja del 79 %
# y los tres malos se quedaron entre el 11 y el 40 %. Término es lo que no se parafrasea:
# siglas, mayúscula interior, cifra o extensión (SOC, PsExec, T1204, ntds.dit).
_TERMINO_RE = re.compile(r"\b(?:[A-Za-z]*[a-z][A-Z][A-Za-z]*|[A-Z]{2,}[A-Za-z0-9]*"
                         r"|[A-Za-z]+\d\w*|\w+\.\w{2,4})\b")
_COBERTURA = 0.6
_MIN_TERMINOS = 4       # con menos, perder uno ya es el 25 % y no dice nada


def _perdidos(texto: str, md: str) -> list[str]:
    """Términos de la transcripción que faltan en las notas, o [] si faltan pocos."""
    terminos = {m.group(0) for m in _TERMINO_RE.finditer(texto)}
    if len(terminos) < _MIN_TERMINOS:
        return []
    bajo = md.lower()
    faltan = sorted(t for t in terminos if t.lower() not in bajo)
    return faltan if len(faltan) > len(terminos) * (1 - _COBERTURA) else []


def _validate(md: str) -> list[str]:
    warnings = []
    if INVALID_RE.search(md):
        warnings.append("Output contains HTML, LaTeX or asterisk lists")
    if md.count("#") == 0:
        warnings.append("No headings found")
    return warnings

def generate_markdown(text: str, lang: str = "es", title: str | None = None) -> str:
    """El .txt convertido en MD academico. API: str (lanza AIError si no hay modelo).

    El modelo sale del registro (src/ai/), asi que el formateo hereda el fallback: el
    429 del preferido ya no deja la fase 0 sin hacer teniendo otro modelo libre.
    `title` es el nombre del fichero de origen: lo unico que sabe de que parte de un
    tema se trata (ver parser.conserva_la_parte). Va tercero y opcional para no romper
    a quien llame con dos argumentos.

    Con `lang="es"` (lo que usa el pipeline) las notas salen en el idioma de la
    transcripción, sea cual sea. Si vuelven en otro dos veces seguidas, AIError:
    load_markdown se queda con el crudo y no guarda el .md, y la próxima lo reintenta.
    Si vuelven resumidas (ver _perdidos) también se reintenta, pero ahí dos fallos no
    son un error: se queda la que conserve más, con un aviso, porque unas notas cortas
    se leen y una transcripción sin encabezados no.
    """
    origen = _idioma(text)
    if lang != "es":
        esperado, lang_note = lang, f"Write the notes in {lang.upper()}."
    else:
        esperado = origen
        cual = f"{_NOMBRES.get(origen, origen.upper())}, " if origen else ""
        lang_note = (f"Write the notes in {cual}the language of the transcription. "
                     "Do not translate it.")
    nombre    = _PREFIJO_NUM_RE.sub("", (title or "").strip())
    title_note = f"Source filename: {nombre}" if nombre else ""
    prompt = "\n\n".join(p for p in (lang_note, title_note, text) if p).strip()

    mejor = None
    for _ in range(2):
        md = _strip_fences(get_model().complete(prompt, system=SYSTEM, temperature=0.2))
        salio = _idioma(md)
        if esperado and salio and salio.split("-")[0] != esperado.split("-")[0]:
            continue
        faltan = _perdidos(text, md)
        if mejor is None or len(faltan) < len(mejor[1]):
            mejor = (md, faltan)
        if not faltan:
            break
    if mejor is None:
        raise AIError(f"the notes came back in {salio.upper()} "
                      f"and the transcription is in {esperado.upper()}")
    md, faltan = mejor
    if title:
        md = conserva_la_parte(md, title)
    avisos = _validate(md)
    if faltan:
        avisos.append(f"Summarized: {len(faltan)} terms of the transcription are "
                      f"missing ({', '.join(faltan[:6])}…)")
    for w in avisos:
        print(f"  Warning: {w}", file=sys.stderr)

    return md

def main():
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("input_file", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--lang", default="es")
    args = ap.parse_args()

    if not args.input_file.exists():
        print(f"ERROR: {args.input_file} not found", file=sys.stderr)
        sys.exit(1)

    text = args.input_file.read_text(encoding="utf-8").strip()
    if not text:
        print("ERROR: input file is empty", file=sys.stderr)
        sys.exit(1)

    out = args.output or (
        args.input_file.with_name(f"{args.input_file.stem}_formatted.md")
        if args.input_file.suffix == ".md"
        else args.input_file.with_suffix(".md")
    )

    try:
        md = generate_markdown(text, args.lang, title=args.input_file.stem)
        out.write_text(md + "\n", encoding="utf-8")
        print(f"✓ {out}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
