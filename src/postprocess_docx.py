"""
postprocess_docx.py — post-proceso del .docx generado por Pandoc.

  1. fix_tables        — tblW=100%, jc=left/right, tblInd=0
  2. fix_blocktext     — spacer tras BlockText (Pandoc ignora after-spacing)
  3. fix_rtl           — bidi + jc=right + indent derecho a todos los párrafos (ar/he/fa/ur)
  4. fix_cjk_fonts     — Noto Sans CJK SC  (zh/ja/ko/vi)
  5. inject_header     — imagen de cabecera (--header path/to/img.png)
  6. inject_page_numbers — número de página en el footer

Usage:
    python postprocess_docx.py output.docx [--lang zh] [--header public/header.png]
"""

import argparse, shutil, struct, tempfile, zipfile
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

# Estilos de párrafo que Pandoc genera — todos necesitan bidi en RTL
PARA_STYLES = {"Normal","BodyText","FirstParagraph","BlockText","Compact",
               "Title","Heading1","Heading2","Heading3","Heading4"}
# Estilos que NO deben ser RTL (código siempre LTR)
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


# ── 1. Tablas ─────────────────────────────────────────────────────────────────
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
        reorder(tblPr, TBLPR_ORDER)


# ── 2. BlockText spacing ──────────────────────────────────────────────────────
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


# ── 3. RTL: bidi + jc=right + indent derecho en cada párrafo ─────────────────
def fix_rtl(body):
    """
    Pandoc no propaga bidi/jc de los estilos a los párrafos del documento.
    Lo inyectamos inline en cada párrafo excepto bloques de código.
    """
    for p in body.findall(f".//{w('p')}"):
        pPr = p.find(w("pPr"))
        if pPr is None:
            pPr = etree.SubElement(p, w("pPr"))
            p.insert(0, pPr)

        # Detectar si es código (LTR siempre)
        ps = pPr.find(w("pStyle"))
        style = ps.get(w("val")) if ps is not None else "Normal"
        if style in LTR_STYLES:
            continue

        # bidi
        bidi = pPr.find(w("bidi"))
        if bidi is None: bidi = etree.SubElement(pPr, w("bidi"))
        bidi.set(w("val"), "1")

        # jc=left + bidi=1 = alineación derecha visual en RTL (comportamiento Word estándar)
        jc = pPr.find(w("jc"))
        if jc is None: jc = etree.SubElement(pPr, w("jc"))
        jc.set(w("val"), "left")

        reorder(pPr, PPR_ORDER)

    # También activar bidi en los runs de texto árabe
    for r_el in body.findall(f".//{w('r')}"):
        rPr = r_el.find(w("rPr"))
        if rPr is None:
            rPr = etree.SubElement(r_el, w("rPr"))
            r_el.insert(0, rPr)
        rtl_el = rPr.find(w("rtl"))
        if rtl_el is None:
            rtl_el = etree.SubElement(rPr, w("rtl"))
        rtl_el.set(w("val"), "1")


# ── 4. CJK fonts ──────────────────────────────────────────────────────────────
def fix_cjk_fonts(doc_root, styles_root):
    for rFonts in list(doc_root.findall(f".//{w('rFonts')}")) + \
                  list(styles_root.findall(f".//{w('rFonts')}")):
        for attr in [w("ascii"), w("hAnsi"), w("cs"), w("eastAsia")]:
            rFonts.set(attr, CJK_FONT)


# ── 5. Header image ───────────────────────────────────────────────────────────
def inject_header(tmp: Path, img: Path):
    with open(img, 'rb') as f:
        f.read(16)
        iw = struct.unpack('>I', f.read(4))[0]
        ih = struct.unpack('>I', f.read(4))[0]
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


# ── 6. Page numbers in footer ─────────────────────────────────────────────────
def inject_page_numbers(tmp: Path, rtl=False):
    jc_val = "right" if rtl else "center"

    (tmp / "word" / "footer1.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W}">
  <w:p>
    <w:pPr><w:jc w:val="{jc_val}"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r>
    <w:fldSimple w:instr=" PAGE ">
      <w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r>
    </w:fldSimple>
    <w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve"> / </w:t></w:r>
    <w:fldSimple w:instr=" NUMPAGES ">
      <w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r>
    </w:fldSimple>
  </w:p>
</w:ftr>""", encoding="utf-8")

    rels_dir = tmp / "word" / "_rels"
    rels_dir.mkdir(exist_ok=True)
    ftr_rels = rels_dir / "footer1.xml.rels"
    ftr_rels.write_text(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS_NS}"/>""", encoding="utf-8")

    _add_part(tmp, "/word/footer1.xml",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml")
    _add_rel(tmp, "rFtr1", f"{R}/footer", "footer1.xml")
    _link_footer_in_sectPr(tmp, "rFtr1")


# ── Helpers para rels / content types / sectPr ───────────────────────────────
def _add_part(tmp, part_name, content_type):
    ct_path = tmp / "[Content_Types].xml"
    ct = etree.parse(str(ct_path)).getroot()
    if not any(e.get("PartName") == part_name for e in ct.findall(f"{{{CT}}}Override")):
        e = etree.SubElement(ct, f"{{{CT}}}Override")
        e.set("PartName", part_name)
        e.set("ContentType", content_type)
    # png default
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
    if sectPr.find(w("titlePg")) is None: etree.SubElement(sectPr, w("titlePg"))
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
    if sectPr.find(w("titlePg")) is None: etree.SubElement(sectPr, w("titlePg"))
    etree.ElementTree(doc).write(str(tmp / "word" / "document.xml"),
                                 xml_declaration=True, encoding="UTF-8", standalone=True)


# ── Main ──────────────────────────────────────────────────────────────────────
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

        if rtl:
            fix_rtl(body)

        if cjk:
            fix_cjk_fonts(doc.getroot(), styles.getroot())
            styles.write(str(styles_xml), xml_declaration=True,
                         encoding="UTF-8", standalone=True)

        doc.write(str(doc_xml), xml_declaration=True, encoding="UTF-8", standalone=True)

        inject_page_numbers(tmp, rtl=rtl)

        if header and header.exists():
            _add_png_type(tmp)
            inject_header(tmp, header)

        out = docx_path.with_suffix(".tmp.docx")
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in tmp.rglob("*"):
                if f.is_file(): z.write(f, f.relative_to(tmp))
        shutil.move(str(out), str(docx_path))
        print(f"✓ {docx_path.name}  lang={lang or 'ltr'}  rtl={rtl}  cjk={cjk}")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", type=Path)
    ap.add_argument("--lang",   default="")
    ap.add_argument("--header", type=Path, default=None)
    args = ap.parse_args()
    postprocess(args.docx.resolve(), args.lang, args.header)