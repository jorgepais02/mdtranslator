"""Markdown line classifier and rebuilder for the translation pipeline."""

from __future__ import annotations
import re

HEADING_RE  = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BULLET_RE   = re.compile(r"^(\s*)-\s+(.*\S)\s*$")
NUMBER_RE   = re.compile(r"^(\s*)(\d+)\.\s+(.*\S)\s*$")
QUOTE_RE    = re.compile(r"^(>{1,6}\s?)(.*)")
HR_RE       = re.compile(r"^\s*---\s*$")
FENCE_RE    = re.compile(r"^(`{3,}|~{3,})")
TABLE_SEP_RE = re.compile(r"^\|?[\s|:\-]+\|[\s|:\-]*$")  # |---|---| rows

LineInfo = tuple[str, str, str]


def parse_markdown_lines(lines: list[str]) -> list[LineInfo]:
    """Classify each Markdown line and extract translatable text.

    Returns a list of (kind, prefix, text) tuples where:
      - kind:   'blank' | 'hr' | 'heading' | 'bullet' | 'number' |
                'blockquote' | 'table_sep' | 'table_row' | 'body' | 'code_block'
      - prefix: structural marker ('  ' on body lines signals a markdown hard line-break)
      - text:   translatable content (empty for blank/hr/code_block/table_sep)
    """
    parsed: list[LineInfo] = []
    in_code = False
    fence   = ""

    for raw in lines:
        line = raw.rstrip("\n")

        # ── fenced code block ────────────────────────────────────────────
        m = FENCE_RE.match(line)
        if m:
            if not in_code:
                in_code, fence = True, m.group(1)
            elif line.strip().startswith(fence):
                in_code, fence = False, ""
            parsed.append(("code_block", line, ""))
            continue

        if in_code:
            parsed.append(("code_block", line, ""))
            continue

        # ── blank ────────────────────────────────────────────────────────
        if not line.strip():
            parsed.append(("blank", "", ""))
            continue

        # ── HR (must come before blockquote to avoid --- confusion) ──────
        if HR_RE.match(line):
            parsed.append(("hr", "---", ""))
            continue

        # ── heading ──────────────────────────────────────────────────────
        m = HEADING_RE.match(line)
        if m:
            parsed.append(("heading", m.group(1), m.group(2)))
            continue

        # ── blockquote ───────────────────────────────────────────────────
        m = QUOTE_RE.match(line)
        if m:
            parsed.append(("blockquote", m.group(1), m.group(2).strip()))
            continue

        # ── table separator row (|---|---| — structural, not translatable)
        if TABLE_SEP_RE.match(line):
            parsed.append(("table_sep", line, ""))
            continue

        # ── table data row ───────────────────────────────────────────────
        if line.startswith("|") or ("|" in line and line.strip().startswith("|")):
            parsed.append(("table_row", line, line))
            continue

        # ── bullet list ──────────────────────────────────────────────────
        m = BULLET_RE.match(line)
        if m:
            parsed.append(("bullet", m.group(1), m.group(2)))
            continue

        # ── numbered list ─────────────────────────────────────────────────
        m = NUMBER_RE.match(line)
        if m:
            parsed.append(("number", f"{m.group(1)}{m.group(2)}.", m.group(3)))
            continue

        # ── body paragraph ───────────────────────────────────────────────
        # Preserve trailing "  " (markdown hard line-break) in the prefix slot.
        linebreak = "  " if line.endswith("  ") else ""
        parsed.append(("body", linebreak, line.strip()))

    return parsed


def rebuild_markdown_from_translations(
    parsed: list[LineInfo], translated_texts: list[str]
) -> list[str]:
    """Reconstruct the Markdown document using translated texts in order."""
    out: list[str] = []
    t_idx = 0

    for kind, prefix, original in parsed:
        if kind == "blank":
            out.append("")
        elif kind == "hr":
            out.append("---")
        elif kind == "code_block":
            out.append(prefix)
        elif kind == "table_sep":
            out.append(prefix)
        elif kind == "heading":
            out.append(f"{prefix} {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "blockquote":
            out.append(f"{prefix}{translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "bullet":
            out.append(f"{prefix}- {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "number":
            out.append(f"{prefix} {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "table_row":
            out.append(translated_texts[t_idx])
            t_idx += 1
        elif kind == "body":
            # prefix is "  " when original line had a markdown hard line-break
            out.append(translated_texts[t_idx] + prefix)
            t_idx += 1

    return out
