"""
Convierte texto raw en MD académico con Gemini.

API:
    generate_markdown(text: str, lang: str = "es") -> str

CLI:
    python -m src.integrations.generate_md input.txt [-o output.md] [--lang es]
"""

import argparse, re, sys
from pathlib import Path

# Dos formas de llegar aqui: importado por la CLI (con src/ en sys.path) o ejecutado
# con python -m src.integrations.generate_md. El relativo solo vale en el segundo caso.
try:
    from ..ai.registry import get_model
except ImportError:
    from ai.registry import get_model

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
- Remove greetings, author names, URLs, chapter numbers from titles
- If the original title contains part indicators like (I), (II), (III) or similar, you MUST preserve them in the final title, including the parentheses.
- No decorative separators (---)
- Technical, neutral, academic tone
- Return ONLY the Markdown content"""

INVALID_RE = re.compile(r'(<[a-z]+[\s>]|\$\$|^\* )', re.MULTILINE)

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    # Y sin espacios al final de linea: en Markdown dos espacios son un salto forzado
    # y Pandoc los mete como <br> en medio del parrafo. Ver refiner._una_llamada, que
    # es donde se vio: openai/gpt-oss-120b cierra con ellos casi cada linea.
    return "\n".join(l.rstrip() for l in text.strip().splitlines())

def _validate(md: str) -> list[str]:
    warnings = []
    if INVALID_RE.search(md):
        warnings.append("Output contains HTML, LaTeX or asterisk lists")
    if md.count("#") == 0:
        warnings.append("No headings found")
    return warnings

def generate_markdown(text: str, lang: str = "es") -> str:
    """El .txt convertido en MD academico. API: str (lanza AIError si no hay modelo).

    El modelo sale del registro (src/ai/), asi que el formateo hereda el fallback: el
    429 del preferido ya no deja la fase 0 sin hacer teniendo otro modelo libre.
    """
    lang_note = f"Write the notes in {lang.upper()}." if lang != "es" else ""
    prompt = f"{lang_note}\n\n{text}".strip()

    md = _strip_fences(get_model().complete(prompt, system=SYSTEM, temperature=0.2))
    for w in _validate(md):
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
        md = generate_markdown(text, args.lang)
        out.write_text(md + "\n", encoding="utf-8")
        print(f"✓ {out}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
