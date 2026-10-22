# -*- coding: utf-8 -*-
"""Extract slide text (and speaker notes) from .pptx with the standard library.

A .pptx is a zip of OOXML parts:

    ppt/presentation.xml        <p:sldIdLst> gives the slide order
    ppt/_rels/presentation.xml.rels   maps r:id -> slides/slideN.xml
    ppt/slides/slideN.xml       shapes; visible text lives in <a:t>
    ppt/notesSlides/notesSlideN.xml   speaker notes (often the real explanation)

No python-pptx, no lxml — just zipfile + ElementTree.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_SKIP_NOTES = re.compile(r"^\d+$")


class PptxError(Exception):
    pass


def _rels(zf: zipfile.ZipFile, part: str) -> dict:
    """Map relationship id -> resolved target part name for `part`."""
    folder, _, name = part.rpartition("/")
    rels_name = "%s/_rels/%s.rels" % (folder, name) if folder else "_rels/%s.rels" % name
    if rels_name not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_name))
    out = {}
    for rel in root.findall(PKG_REL + "Relationship"):
        target = rel.get("Target") or ""
        if target.startswith("/"):
            resolved = target.lstrip("/")
        elif target.startswith("../"):
            base = folder
            while target.startswith("../"):
                target = target[3:]
                base = base.rpartition("/")[0]
            resolved = (base + "/" + target) if base else target
        else:
            resolved = "%s/%s" % (folder, target) if folder else target
        out[rel.get("Id")] = resolved
    return out


def _paragraph_text(el) -> str:
    return "".join(t.text or "" for t in el.iter(A + "t"))


def _shape_lines(root) -> list:
    """Visible text of a slide, one string per shape paragraph."""
    lines = []
    sp_tree = root.find(".//" + P + "cSld/" + P + "spTree")
    if sp_tree is None:
        sp_tree = root
    for shape in list(sp_tree):
        paragraphs = shape.findall(".//" + A + "p")
        if not paragraphs:
            continue
        for para in paragraphs:
            text = _paragraph_text(para).strip()
            text = re.sub(r"^[•·\-–—]\s*", "", text)
            if text:
                lines.append(text)
    return lines


def _slide_order(zf: zipfile.ZipFile) -> list:
    pres = ET.fromstring(zf.read("ppt/presentation.xml"))
    rels = _rels(zf, "ppt/presentation.xml")
    order = []
    lst = pres.find(P + "sldIdLst")
    if lst is None:
        return order
    for sld in lst.findall(P + "sldId"):
        rid = sld.get(R + "id")
        target = rels.get(rid)
        if target and target in zf.namelist():
            order.append(target)
    if not order:  # malformed file: fall back to numeric part order
        parts = [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        order = sorted(parts, key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
    return order


def _notes_for(zf: zipfile.ZipFile, slide_part: str) -> str:
    rels = _rels(zf, slide_part)
    for target in rels.values():
        if "notesSlide" in target and target in zf.namelist():
            try:
                root = ET.fromstring(zf.read(target))
            except ET.ParseError:
                return ""
            lines = []
            for para in root.iter(A + "p"):
                text = _paragraph_text(para).strip()
                if text and not _SKIP_NOTES.match(text):
                    lines.append(text)
            return "\n".join(lines)
    return ""


def extract_pages(path_or_bytes) -> list:
    """Return [{'n': 1, 'text': ...}, ...] for a .pptx."""
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            import io

            zf = zipfile.ZipFile(io.BytesIO(bytes(path_or_bytes)))
        else:
            zf = zipfile.ZipFile(path_or_bytes)
    except zipfile.BadZipFile:
        raise PptxError("这不是一个有效的 .pptx（zip 结构打不开）") from None

    with zf:
        if "ppt/presentation.xml" not in zf.namelist():
            raise PptxError("找不到 ppt/presentation.xml，可能不是 PPTX 文件")

        pages = []
        for idx, part in enumerate(_slide_order(zf), 1):
            try:
                root = ET.fromstring(zf.read(part))
            except ET.ParseError:
                pages.append({"n": idx, "text": ""})
                continue
            lines = _shape_lines(root)
            notes = _notes_for(zf, part)
            text = "\n".join(lines)
            if notes:
                text += ("\n" if text else "") + "（备注）" + notes
            pages.append({"n": idx, "text": text.strip()})
        return pages


def is_ppt_legacy(name: str) -> bool:
    return name.lower().endswith(".ppt")
