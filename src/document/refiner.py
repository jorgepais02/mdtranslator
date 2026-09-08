"""
Refinamiento nodo a nodo de MD traducido con Gemini.

Estrategia:
  - Parsear el MD en nodos tipados
  - Mandar a Gemini SOLO texto plano (paragraph, list_item, blockquote)
  - Los inline spans se extraen como placeholders antes de Gemini
  - El MD de salida es estructuralmente idéntico al de entrada

Nodos refinables:  paragraph, list_item, blockquote
Nodos intocables:  heading, code_block, table, hr, blank, frontmatter
"""

import os, re
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

def _call_gemini(texts: list[str], lang: str, client) -> tuple[list[str], str | None]:
    if not texts:
        return [], None
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

def refine_markdown(lines: list[str], lang_code: str) -> tuple[list[str], str | None]:
    """Refina un MD traducido. Devuelve (líneas, warning_o_None) sin imprimir nada."""
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

    refined = []
    try:
        for start in range(0, len(texts), BATCH):
            batch_out, warn = _call_gemini(texts[start:start + BATCH], lang_code, client)
            refined += batch_out
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
