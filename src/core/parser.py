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

# Las listas con letra ("A)", "b)", "c."): Pandoc las convierte en una lista de verdad, así
# que la letra es estructura y no texto. Mandándola al traductor, el árabe la devolvía
# como "أ)" y el chino como "A）": Pandoc dejaba de ver la lista —se iba la sangría— y una
# solución que decía "C" ya no apuntaba a ninguna opción. "A." con un solo espacio no
# cuenta, igual que para Pandoc: "B. Russell fue un filósofo" es prosa, no el punto B.
LETRA_DE_LISTA = r"[A-Za-z]\)|[a-z]\."
LETTER_RE   = re.compile(rf"^(\s*)({LETRA_DE_LISTA})\s+(.*\S)\s*$")

LineInfo = tuple[str, str, str]

# La parte de un tema repartido en varios apuntes, tal y como la escribe el nombre del
# fichero: "… (I)", "… (II)", "… (III)". Solo romanos hasta XX y arábigos de dos cifras,
# y anclado al final: un título que acaba en "(DFIR)" o "(ECU)" no es la parte de nada, y
# colgársela al encabezado sería inventarse una serie que no existe.
_ROMANOS  = sorted("I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX".split(),
                   key=len, reverse=True)
_PARTE_RE = re.compile(r"\s*\((" + "|".join(_ROMANOS) + r"|\d{1,2})\)\s*$")

# Los espacios de los extremos, pero no el salto de línea: con \s* el final del patrón se
# come el \n y el título se pega al párrafo siguiente.
_H1_RE = re.compile(r"^(#[ \t]+)(.+?)[ \t]*$", re.MULTILINE)


def parte_de(nombre: str) -> str:
    """El indicador de parte de un nombre. API: "(II)", o "" si no lo lleva."""
    m = _PARTE_RE.search(nombre)
    return f"({m.group(1)})" if m else ""


def quita_la_parte(md: str) -> str:
    """El Markdown con el "(II)" fuera del título. API: str.

    Se quita antes de traducir porque el indicador **no es contenido**: es la posición
    del documento en una serie. Mandándoselo al traductor, el árabe lo convertía en
    "(الجزء الأول)" y el chino en "（一）" mientras su hermano decía "（II）" — tres
    convenciones en la misma carpeta. Y de paso el texto que viaja vuelve a ser el mismo
    de siempre, así que la caché sigue acertando y la traducción no cambia por haberle
    pegado un paréntesis: al añadirlo, "Técnicas de Extracción Invasivas" pasó de
    "侵入性提取技术" a "侵入性拔牙技术" —extracción dental—.
    """
    m = _H1_RE.search(md)
    if not m:
        return md
    limpio = _PARTE_RE.sub("", m.group(2))
    return md[:m.start()] + f"{m.group(1)}{limpio}" + md[m.end():]


def conserva_la_parte(md: str, nombre: str) -> str:
    """El Markdown con el "(II)" del nombre del fichero pegado al título. API: str.

    El (I)/(II)/(III) distingue las partes de un mismo tema y vive **solo en el nombre
    del fichero**: el .txt es la transcripción hablada y no lo menciona, así que el
    modelo que escribe el título no tiene de dónde sacarlo por mucho que se lo pidan.
    Se impone en vez de pedirse porque un modelo obedece casi siempre, y "casi siempre"
    aquí se ve en la pantalla del usuario.
    """
    parte = parte_de(nombre)
    if not parte:
        return md
    m = _H1_RE.search(md)
    if not m:
        return md
    # Si el modelo puso una parte por su cuenta manda la del fichero, o convivirían dos
    # convenciones ("(2)" y "(II)") en la misma carpeta.
    limpio = _PARTE_RE.sub("", m.group(2))
    return md[:m.start()] + f"{m.group(1)}{limpio} {parte}" + md[m.end():]


# De qué van estos apuntes, para que el traductor elija la acepción correcta. Sale del
# propio documento —el título y su párrafo de resumen— y no de un glosario escrito a mano,
# porque cada módulo habla de otra cosa y las palabras que se vuelven ambiguas no se saben
# de antemano. El tope existe porque es contexto, no contenido: DeepL lo recorta y un
# prompt con medio documento dentro deja de ser una pista.
_TOPE_CONTEXTO = 600

# Lo que no es prosa: listas, tablas, citas, vallas de código y encabezados. Una lista de
# viñetas dice de qué va el documento mucho peor que su párrafo de entrada.
_NO_ES_PROSA_RE = re.compile(rf"^\s*(#|-|\*|>|\||`{{3,}}|~{{3,}}|\d+[.)]\s|(?:{LETRA_DE_LISTA})\s)")


def contexto_del_documento(md: str, tope: int = _TOPE_CONTEXTO) -> str:
    """El título y el resumen del documento, en una cadena. API: str, "" si no hay.

    Va al traductor como contexto y no se traduce: "Selección del Origen" a secas daba
    en chino "产地选择" —la procedencia de un producto— y "Análisis Forense" daba
    "法医分析", el forense de las autopsias. Con el contexto delante salen "来源选择" y
    "取证分析", que es lo que dicen los apuntes. El defecto no es del traductor: cada
    línea viaja sola y "forense" en español es las dos cosas.
    """
    lineas = md.splitlines()
    m = None
    for i, linea in enumerate(lineas):
        m = HEADING_RE.match(linea)
        if m and len(m.group(1)) == 1:
            break
        m = None
    if m is None:
        return ""

    piezas = [m.group(2).strip()]
    largo  = len(piezas[0])
    # No se para en el primer "##": hay apuntes que van del título a la primera sección
    # sin entradilla, y ahí el contexto se quedaba en cuatro palabras. "Técnicas de
    # Extracción Invasivas" a secas no dice si la extracción es de datos o de muelas —y
    # el chino eligió muelas—, así que se sigue recogiendo prosa por debajo.
    dentro_de_valla = False
    for linea in lineas[i + 1:]:
        if largo >= tope:
            break
        # La valla hay que seguirla, no solo reconocerla: filtrando únicamente la línea
        # de los backticks, el `dd if=/dev/sda` de dentro se colaba como si fuera prosa.
        if FENCE_RE.match(linea.strip()):
            dentro_de_valla = not dentro_de_valla
            continue
        if dentro_de_valla or not linea.strip() or _NO_ES_PROSA_RE.match(linea):
            continue
        piezas.append(linea.strip())
        largo += len(linea)

    return _hasta_la_ultima_palabra(" ".join(piezas), tope)


def _hasta_la_ultima_palabra(texto: str, tope: int) -> str:
    """El texto recortado al tope sin partir la última palabra. API: str."""
    if len(texto) <= tope:
        return texto
    corte = texto.rfind(" ", 0, tope)
    return texto[:corte if corte > 0 else tope].rstrip()


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

        # ── lettered list: "A)" viaja como prefijo, igual que "1." ─────────
        m = LETTER_RE.match(line)
        if m:
            parsed.append(("number", f"{m.group(1)}{m.group(2)}", m.group(3)))
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

    def _next(original: str) -> str:
        """Take the next translation for a line, or keep the original.

        Only non-empty text is sent to a provider, so a structural line with no
        content — a bare '>' between two quoted paragraphs, say — must not consume
        a slot or every later line shifts by one. A short or incomplete provider
        response degrades to the original text instead of raising or writing None.
        """
        nonlocal t_idx
        if not original:
            return original
        if t_idx >= len(translated_texts):
            return original
        value = translated_texts[t_idx]
        t_idx += 1
        return original if value is None else value

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
            out.append(f"{prefix} {_next(original)}")
        elif kind == "blockquote":
            out.append(f"{prefix}{_next(original)}")
        elif kind == "bullet":
            out.append(f"{prefix}- {_next(original)}")
        elif kind == "number":
            out.append(f"{prefix} {_next(original)}")
        elif kind == "table_row":
            out.append(_next(original))
        elif kind == "body":
            # prefix is "  " when original line had a markdown hard line-break
            out.append(_next(original) + prefix)

    return out
