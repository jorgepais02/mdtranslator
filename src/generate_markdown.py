"""
generate_markdown.py — Convierte texto raw en MD académico con Gemini.

API:
    generate_markdown(text: str, lang: str = "es") -> str

CLI:
    python generate_markdown.py input.txt [-o output.md] [--lang es]
"""

import argparse, os, re, sys
from pathlib import Path
from google import genai
from google.genai import types

SYSTEM = """You are an academic note-taking assistant.
Convert raw transcriptions into clean, structured Markdown notes.

Rules:
- Use # for title, ## for sections, ### for subsections
- Prefer paragraphs over lists — use lists only when content is genuinely enumerable
- Lists use only "- " (never asterisks)
- Ordered steps use "1. 2. 3."
- Never fake headings with **bold** inside lists
- Each heading must be followed by at least one paragraph before any list
- Remove greetings, author names, URLs, chapter numbers from titles
- No decorative separators (---)
- Technical, neutral, academic tone
- Return ONLY the Markdown content"""

# Elementos que no deberían aparecer en el output
INVALID_RE = re.compile(r'(<[a-z]+[\s>]|\$\$|^\* )', re.MULTILINE)

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```[a-z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return text.strip()

def _validate(md: str) -> list[str]:
    """Devuelve lista de warnings. Pipeline decide si bloquear o no."""
    warnings = []
    if INVALID_RE.search(md):
        warnings.append("Output contains HTML, LaTeX or asterisk lists")
    if md.count("#") == 0:
        warnings.append("No headings found")
    return warnings

def generate_markdown(text: str, lang: str = "es") -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set")

    lang_note = f"Write the notes in {lang.upper()}." if lang != "es" else ""
    prompt = f"{lang_note}\n\n{text}".strip()

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            temperature=0.2,
        ),
    )

    md = _strip_fences(resp.text or "")
    warnings = _validate(md)
    for w in warnings:
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