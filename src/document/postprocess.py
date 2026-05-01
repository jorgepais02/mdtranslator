"""
Post-proceso del .docx generado por Pandoc.

  1. fix_tables        — tblW=100%, jc=left/right, tblInd=0
  2. fix_blocktext     — spacer tras BlockText
  3. fix_rtl           — bidi + jc=right + indent derecho (ar/he/fa/ur)
  4. fix_cjk_fonts     — Noto Sans CJK SC (zh/ja/ko/vi)
  5. inject_header     — imagen de cabecera
  6. inject_page_numbers — número de página en el footer

Usage:
    python -m src.document.postprocess output.docx [--lang zh] [--header public/header.png]
"""

import argparse, shutil, tempfile, zipfile
from pathlib import Path
from lxml import etree

W       = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R       = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT      = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

def w(t): return f"{{{W}}}{t}"
def r(t): return f"{{{R}}}{t}"

CJK_LANGS = {"zh", "ja", "ko", "vi"}
RTL_LANGS = {"ar", "he", "fa", "ur"}
CJK_FONT  = "Noto Sans CJK SC"

PARA_STYLES = {"Normal","BodyText","FirstParagraph","BlockText","Compact",
               "Title","Heading1","Heading2","Heading3","Heading4"}
LTR_STYLES  = {"SourceCode","VerbatimChar"}

TBLPR_ORDER = ["tblStyle","tblpPr","tblOverlap","bidiVisual","tblStyleRowBandSize",
               "tblStyleColBandSize","tblW","jc","tblInd","tblBorders","shd",
               "tblLayout","tblCellMar","tblLook","tblCaption","tblDescription"]
PPR_ORDER   = ["pStyle","keepNext","keepLines","pageBreakBefore","suppressLineNumbers",
               "pBdr","shd","tabs","suppressAutoHyphens","kinsoku","wordWrap",
               "overflowPunct","topLinePunct","autoSpaceDE","autoSpaceDN","bidi",
               "adjustRightInd","snapToGrid","spacing","ind","contextualSpacing",
               "mirrorIndents","suppressOverlap","jc","textDirection","textAlignment",
               "textboxTightWrap","outlineLvl","divId","cnfStyle","rPr","sectPr","pPrChange"]

def reorder(parent, order):
    children = sorted(list(parent),
        key=lambda el: order.index(el.tag.split('}')[-1])
                       if el.tag.split('}')[-1] in order else 999)
    for c in list(parent): parent.remove(c)
    for c in children: parent.append(c)

def set_el(parent, tag, attrs):
    el = parent.find(w(tag))
    if el is None: el = etree.SubElement(parent, w(tag))
    el.attrib.update(attrs)
    return el


INLINE_SPACING = {
    "Title":          {"before": "0",   "after": "360", "line": "360", "lineRule": "auto"},
    "Heading1":       {"before": "320", "after": "120", "line": "360", "lineRule": "auto"},
    "Heading2":       {"before": "260", "after": "120", "line": "360", "lineRule": "auto"},
    "Heading3":       {"before": "200", "after": "100", "line": "360", "lineRule": "auto"},
    "Heading4":       {"before": "160", "after": "80",  "line": "360", "lineRule": "auto"},
    "FirstParagraph": {"before": "0",   "after": "160", "line": "360", "lineRule": "auto"},
    "BodyText":       {"before": "0",   "after": "160", "line": "360", "lineRule": "auto"},
    "Compact":        {"before": "0",   "after": "80",  "line": "360", "lineRule": "auto"},
    "SourceCode":     {"before": "160", "after": "160", "line": "240", "lineRule": "auto"},
}
_LIST_TAIL_AFTER = "220"

def fix_inline_spacing(body):
    """Apply spacing inline on every paragraph — survives Google Drive and LibreOffice round-trips."""
    paras = body.findall(w("p"))
    for i, p in enumerate(paras):
        pPr = p.find(w("pPr"))
        if pPr is None:
            pPr = etree.SubElement(p, w("pPr"))
            p.insert(0, pPr)

        ps = pPr.find(w("pStyle"))
        style_id = ps.get(w("val"), "") if ps is not None else ""

        target = INLINE_SPACING.get(style_id)
        if target is None:
            continue

        spacing = pPr.find(w("spacing"))
        if spacing is None:
            spacing = etree.SubElement(pPr, w("spacing"))
        for attr, val in target.items():
            spacing.set(w(attr), val)

        # last item of a list block gets extra breathing room
        if style_id == "Compact":
            next_p  = paras[i + 1] if i + 1 < len(paras) else None
            next_pPr = next_p.find(w("pPr")) if next_p is not None else None
            next_ps  = next_pPr.find(w("pStyle")) if next_pPr is not None else None
            next_style = next_ps.get(w("val"), "") if next_ps is not None else ""
            if next_style != "Compact":
                spacing.set(w("after"), _LIST_TAIL_AFTER)


_CELL_SPACING = {"before": "60", "after": "60", "line": "276", "lineRule": "auto"}
_HEADER_FILL  = "E2E2E2"
_BORDER_COLOR = "BFBFBF"

def fix_tables(body, rtl=False):
    jc_val = "right" if rtl else "left"
    for tbl in body.findall(f".//{w('tbl')}"):
        tblPr = tbl.find(w("tblPr"))
        if tblPr is None:
            tblPr = etree.SubElement(tbl, w("tblPr"))
            tbl.insert(0, tblPr)

        set_el(tblPr, "tblW",   {w("w"): "5000", w("type"): "pct"})
        set_el(tblPr, "jc",     {w("val"): jc_val})
        set_el(tblPr, "tblInd", {w("w"): "0", w("type"): "dxa"})
        if rtl:
            set_el(tblPr, "bidiVisual", {w("val"): "1"})

        # clean thin borders
        borders = set_el(tblPr, "tblBorders", {})
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            set_el(borders, side, {w("val"): "single", w("sz"): "4",
                                   w("space"): "0", w("color"): _BORDER_COLOR})

        # cell padding
        mar = set_el(tblPr, "tblCellMar", {})
        for side, val in (("top", "80"), ("left", "120"), ("bottom", "80"), ("right", "120")):
            set_el(mar, side, {w("w"): val, w("type"): "dxa"})

        reorder(tblPr, TBLPR_ORDER)

        # insert a spacer paragraph after the table — Google ignores before on post-table paragraphs
        spacer = etree.Element(w("p"))
        sp = etree.SubElement(etree.SubElement(spacer, w("pPr")), w("spacing"))
        sp.set(w("before"), "0")
        sp.set(w("after"), "200")
        tbl.addnext(spacer)

        # per-row: header shading + cell paragraph spacing
        rows = tbl.findall(w("tr"))
        for i, tr in enumerate(rows):
            is_last_row = (i == len(rows) - 1)
            for tc in tr.findall(w("tc")):
                tcPr = tc.find(w("tcPr"))
                if tcPr is None:
                    tcPr = etree.SubElement(tc, w("tcPr"))
                    tc.insert(0, tcPr)
                if i == 0:
                    set_el(tcPr, "shd", {w("val"): "clear",
                                         w("color"): "auto", w("fill"): _HEADER_FILL})
                cell_paras = tc.findall(w("p"))
                for j, p in enumerate(cell_paras):
                    pPr = p.find(w("pPr"))
                    if pPr is None:
                        pPr = etree.SubElement(p, w("pPr"))
                        p.insert(0, pPr)
                    sp = pPr.find(w("spacing"))
                    if sp is None:
                        sp = etree.SubElement(pPr, w("spacing"))
                    for attr, val in _CELL_SPACING.items():
                        sp.set(w(attr), val)
                    # last paragraph of last row gets extra after to separate from next block
                    if is_last_row and j == len(cell_paras) - 1:
                        sp.set(w("after"), "200")


def fix_blocktext_spacing(body):
    children = list(body)
    inserts = []
    for i, el in enumerate(children):
        if el.tag != w("p"): continue
        pPr = el.find(w("pPr"))
        if pPr is None: continue
        ps = pPr.find(w("pStyle"))
        if ps is None or ps.get(w("val")) != "BlockText": continue
        spacer = etree.Element(w("p"))
        sp = etree.SubElement(etree.SubElement(spacer, w("pPr")), w("spacing"))
        sp.set(w("before"), "0")
        sp.set(w("after"),  "200")
        inserts.append((i + 1, spacer))
    for idx, spacer in reversed(inserts):
        body.insert(idx, spacer)


def fix_rtl(body):
    """Inyecta bidi/jc inline en cada párrafo — Pandoc no propaga los estilos RTL."""
    for p in body.findall(f".//{w('p')}"):
        pPr = p.find(w("pPr"))
        if pPr is None:
            pPr = etree.SubElement(p, w("pPr"))
            p.insert(0, pPr)
        ps = pPr.find(w("pStyle"))
        style = ps.get(w("val")) if ps is not None else "Normal"
        if style in LTR_STYLES:
            continue
        bidi = pPr.find(w("bidi"))
        if bidi is None: bidi = etree.SubElement(pPr, w("bidi"))
        bidi.set(w("val"), "1")
        jc = pPr.find(w("jc"))
        if jc is None: jc = etree.SubElement(pPr, w("jc"))
        jc.set(w("val"), "left")
        reorder(pPr, PPR_ORDER)
    for r_el in body.findall(f".//{w('r')}"):
        rPr = r_el.find(w("rPr"))
        if rPr is None:
            rPr = etree.SubElement(r_el, w("rPr"))
            r_el.insert(0, rPr)
        rtl_el = rPr.find(w("rtl"))
        if rtl_el is None:
            rtl_el = etree.SubElement(rPr, w("rtl"))
        rtl_el.set(w("val"), "1")


def fix_cjk_fonts(doc_root, styles_root):
    for rFonts in list(doc_root.findall(f".//{w('rFonts')}")) + \
                  list(styles_root.findall(f".//{w('rFonts')}")):
        for attr in [w("ascii"), w("hAnsi"), w("cs"), w("eastAsia")]:
            rFonts.set(attr, CJK_FONT)


def inject_header(tmp: Path, img: Path):
    from PIL import Image
    with Image.open(img) as _im:
        iw, ih = _im.size
    MAX = 5_760_000
    ew = min(iw * 9525, MAX)
    eh = int(ih * 9525 * ew / (iw * 9525))

    media = tmp / "word" / "media"
    media.mkdir(exist_ok=True)
    shutil.copy(img, media / "header_img.png")

    (tmp / "word" / "header1.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{W}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
       xmlns:r="{R}">
  <w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:drawing>
    <wp:inline><wp:extent cx="{ew}" cy="{eh}"/>
      <wp:effectExtent l="0" t="0" r="0" b="0"/>
      <wp:docPr id="1" name="HeaderImage"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="HeaderImage"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip r:embed="rImgHdr"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{ew}" cy="{eh}"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
        </pic:pic></a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
</w:hdr>""", encoding="utf-8")

    rels_dir = tmp / "word" / "_rels"
    rels_dir.mkdir(exist_ok=True)
    (rels_dir / "header1.xml.rels").write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS_NS}">
  <Relationship Id="rImgHdr" Type="{R}/image" Target="media/header_img.png"/>
</Relationships>""", encoding="utf-8")

    _add_part(tmp, "/word/header1.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml")
    _add_rel(tmp, "rHdr1", f"{R}/header", "header1.xml")
    _link_header_in_sectPr(tmp, "rHdr1")


def inject_page_numbers(tmp: Path, lang: str, rtl=False):
    # Algunos lectores ignoran el formato localizado de OOXML — omitimos paginación para evitar "1,2,3" occidental
    if lang in {"ar", "fa", "ur", "he", "zh", "ja", "ko"}:
        _remove_footer(tmp)
        return

    jc_val = "right" if rtl else "center"
    numFmt = ""
    w_lang = ""
    if lang == "ar":
        numFmt = "ArabicIndic"
        w_lang = '<w:lang w:val="ar-SA" w:bidi="ar-SA"/>'
    elif lang in ["fa", "ur"]:
        numFmt = "ArabicIndic"
        w_lang = '<w:lang w:val="fa-IR" w:bidi="fa-IR"/>'
    elif lang == "zh":
        numFmt = "CHINESECOUNTING"
        w_lang = '<w:lang w:val="zh-CN" w:eastAsia="zh-CN"/>'
    elif lang == "ja":
        numFmt = "Aiueo"
        w_lang = '<w:lang w:val="ja-JP" w:eastAsia="ja-JP"/>'
    elif lang == "he":
        numFmt = "hebrew2"
        w_lang = '<w:lang w:val="he-IL" w:bidi="he-IL"/>'

    fmt_str = f" \\* {numFmt} " if numFmt else " "
    pPr_extra = '<w:bidi w:val="1"/>' if rtl else ''
    rPr_extra = (w_lang if w_lang else '') + ('<w:rtl w:val="1"/>' if rtl else '')

    (tmp / "word" / "footer1.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W}">
  <w:p>
    <w:pPr><w:jc w:val="{jc_val}"/>{pPr_extra}</w:pPr>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:instrText xml:space="preserve"> PAGE{fmt_str}</w:instrText></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:t>1</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="end"/></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:t xml:space="preserve"> / </w:t></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:instrText xml:space="preserve"> NUMPAGES{fmt_str}</w:instrText></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:t>1</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="18"/>{rPr_extra}</w:rPr><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>""", encoding="utf-8")

    rels_dir = tmp / "word" / "_rels"
    rels_dir.mkdir(exist_ok=True)
    (rels_dir / "footer1.xml.rels").write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS_NS}"/>""", encoding="utf-8")

    _add_part(tmp, "/word/footer1.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml")
    _add_rel(tmp, "rFtr1", f"{R}/footer", "footer1.xml")
    _link_footer_in_sectPr(tmp, "rFtr1")


def _add_part(tmp, part_name, content_type):
    ct_path = tmp / "[Content_Types].xml"
    ct = etree.parse(str(ct_path)).getroot()
    if not any(e.get("PartName") == part_name for e in ct.findall(f"{{{CT}}}Override")):
        e = etree.SubElement(ct, f"{{{CT}}}Override")
        e.set("PartName", part_name)
        e.set("ContentType", content_type)
    if "png" in part_name or part_name.endswith(".png"):
        if not any(e.get("Extension") == "png" for e in ct.findall(f"{{{CT}}}Default")):
            e = etree.SubElement(ct, f"{{{CT}}}Default")
            e.set("Extension", "png"); e.set("ContentType", "image/png")
    etree.ElementTree(ct).write(str(ct_path), xml_declaration=True,
                                encoding="UTF-8", standalone=True)

def _add_png_type(tmp):
    ct_path = tmp / "[Content_Types].xml"
    ct = etree.parse(str(ct_path)).getroot()
    if not any(e.get("Extension") == "png" for e in ct.findall(f"{{{CT}}}Default")):
        e = etree.SubElement(ct, f"{{{CT}}}Default")
        e.set("Extension", "png"); e.set("ContentType", "image/png")
    etree.ElementTree(ct).write(str(ct_path), xml_declaration=True,
                                encoding="UTF-8", standalone=True)

def _add_rel(tmp, rel_id, rel_type, target):
    dr = tmp / "word" / "_rels" / "document.xml.rels"
    drt = etree.parse(str(dr)).getroot()
    if not any(e.get("Id") == rel_id for e in drt):
        e = etree.SubElement(drt, f"{{{RELS_NS}}}Relationship")
        e.set("Id", rel_id); e.set("Type", rel_type); e.set("Target", target)
    etree.ElementTree(drt).write(str(dr), xml_declaration=True,
                                 encoding="UTF-8", standalone=True)

def _link_header_in_sectPr(tmp, rel_id):
    doc = etree.parse(str(tmp / "word" / "document.xml")).getroot()
    sectPr = doc.find(f".//{w('sectPr')}")
    if sectPr is None:
        sectPr = etree.SubElement(doc.find(f".//{w('body')}"), w("sectPr"))
    for hr in sectPr.findall(w("headerReference")): sectPr.remove(hr)
    hr = etree.SubElement(sectPr, w("headerReference"))
    hr.set(w("type"), "default"); hr.set(r("id"), rel_id)
    titlePg = sectPr.find(w("titlePg"))
    if titlePg is not None: sectPr.remove(titlePg)
    etree.ElementTree(doc).write(str(tmp / "word" / "document.xml"),
                                 xml_declaration=True, encoding="UTF-8", standalone=True)

def _link_footer_in_sectPr(tmp, rel_id):
    doc = etree.parse(str(tmp / "word" / "document.xml")).getroot()
    sectPr = doc.find(f".//{w('sectPr')}")
    if sectPr is None:
        sectPr = etree.SubElement(doc.find(f".//{w('body')}"), w("sectPr"))
    for fr in sectPr.findall(w("footerReference")): sectPr.remove(fr)
    fr = etree.SubElement(sectPr, w("footerReference"))
    fr.set(w("type"), "default"); fr.set(r("id"), rel_id)
    titlePg = sectPr.find(w("titlePg"))
    if titlePg is not None: sectPr.remove(titlePg)
    etree.ElementTree(doc).write(str(tmp / "word" / "document.xml"),
                                 xml_declaration=True, encoding="UTF-8", standalone=True)

def _remove_footer(tmp):
    doc_path = tmp / "word" / "document.xml"
    if not doc_path.exists(): return
    doc = etree.parse(str(doc_path)).getroot()
    sectPr = doc.find(f".//{w('sectPr')}")
    if sectPr is not None:
        for fr in sectPr.findall(w("footerReference")):
            sectPr.remove(fr)
        etree.ElementTree(doc).write(str(doc_path), xml_declaration=True, encoding="UTF-8", standalone=True)


def postprocess(docx_path: Path, lang: str = "", header: Path = None):
    rtl = lang in RTL_LANGS
    cjk = lang in CJK_LANGS
    tmp = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(docx_path, 'r') as z: z.extractall(tmp)

        doc_xml    = tmp / "word" / "document.xml"
        styles_xml = tmp / "word" / "styles.xml"
        doc    = etree.parse(str(doc_xml))
        styles = etree.parse(str(styles_xml))
        body   = doc.getroot().find(f".//{w('body')}")

        fix_tables(body, rtl=rtl)
        fix_blocktext_spacing(body)
        fix_inline_spacing(body)
        if rtl:
            fix_rtl(body)
        if cjk:
            fix_cjk_fonts(doc.getroot(), styles.getroot())
            styles.write(str(styles_xml), xml_declaration=True, encoding="UTF-8", standalone=True)

        doc.write(str(doc_xml), xml_declaration=True, encoding="UTF-8", standalone=True)
        inject_page_numbers(tmp, lang=lang, rtl=rtl)
        if header and header.exists():
            _add_png_type(tmp)
            inject_header(tmp, header)

        out = docx_path.with_suffix(".tmp.docx")
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in tmp.rglob("*"):
                if f.is_file(): z.write(f, f.relative_to(tmp))
        shutil.move(str(out), str(docx_path))
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", type=Path)
    ap.add_argument("--lang",   default="")
    ap.add_argument("--header", type=Path, default=None)
    args = ap.parse_args()
    postprocess(args.docx.resolve(), args.lang, args.header)
