# -*- coding: utf-8 -*-
"""Handout ingest: page text, quality verdict, outline and retrieval helpers."""

from __future__ import annotations

import json
import os
import re

from pdftext import PdfDocument

# Characters that only show up when a font has no usable Unicode mapping.
_JUNK = re.compile(
    "[\u2f00-\u2fdf\u3400-\u4dbf\ue000-\uf8ff\ufffd\ufffe\uffff]"
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def _page_quality(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.0
    good = len(_CJK.findall(t)) + len(_LATIN.findall(t))
    junk = len(_JUNK.findall(t))
    return good / max(1, good + 2 * junk)


def build_handout(pdf_path: str, name: str) -> dict:
    """Parse a PDF into a cached handout record."""
    doc = PdfDocument.from_path(pdf_path)
    pages = []
    for i in range(doc.page_count):
        try:
            text = doc.page_text(i)
        except Exception:
            text = ""
        pages.append({"n": i + 1, "text": _clean(text)})

    total_chars = sum(len(p["text"]) for p in pages)
    per_page = total_chars / max(1, len(pages))
    quality_score = (
        sum(_page_quality(p["text"]) for p in pages) / len(pages) if pages else 0.0
    )
    if per_page >= 60 and quality_score >= 0.6:
        quality = "text"
    elif doc.page_count and _has_page_images(doc):
        quality = "scanned"
    elif per_page < 20:
        quality = "vector"          # glyph outlines: no text layer, no page images
    else:
        quality = "poor"

    outline = detect_outline(pages)
    return {
        "name": name,
        "page_count": doc.page_count,
        "chars": total_chars,
        "quality": quality,
        "quality_score": round(quality_score, 3),
        "pages": pages,
        "outline": outline,
    }


def _has_page_images(doc) -> bool:
    """True when at least one page carries a raster image (a scan)."""
    for num in doc.pages[:6]:
        body = doc.body(num)
        res = doc._resource_dict(doc.dict_of(doc.get(num)), 0)
        xo = doc.resolve(res.get("XObject")) if res else None
        if not xo:
            continue
        for ref in (xo or {}).values():
            s = doc.resolve(ref)
            d = doc.dict_of(s)
            if str(doc.resolve(d.get("Subtype")) or "") == "Image":
                return True
    return False


def _clean(text: str) -> str:
    text = text.replace("\u0000", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------
# outline
# --------------------------------------------------------------------------

_HEADINGS = [
    (1, re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇\d]{1,3}\s*[章篇讲部]\s*")),
    (1, re.compile(r"^\s*(Chapter|Part)\s+\d+", re.I)),
    (2, re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇\d]{1,3}\s*节\s*")),
    (2, re.compile(r"^\s*§\s*\d+(\.\d+)*")),
    (2, re.compile(r"^\s*\d+\.\d+(\.\d+)?\s*[、.．:：]?\s*\S")),
    (2, re.compile(r"^\s*[一二三四五六七八九十]{1,2}\s*[、.．]\s*\S")),
    (3, re.compile(r"^\s*[（(]\s*[一二三四五六七八九十]{1,2}\s*[)）]\s*\S")),
    (3, re.compile(r"^\s*\d+\.\d+\.\d+\s*\S")),
]


def detect_outline(pages: list) -> list:
    """Heuristic chapter/section list (a few headings per page at most)."""
    out = []
    for p in pages:
        found = 0
        for line in p["text"].split("\n"):
            if found >= 4:
                break
            s = line.strip()
            if not s or len(s) > 48:
                continue
            for level, pat in _HEADINGS:
                if pat.match(s):
                    title = re.sub(r"\s+", " ", s).strip()
                    if not _looks_like_formula(title):
                        out.append({"page": p["n"], "title": title, "level": level})
                        found += 1
                    break
    return out


def _looks_like_formula(s: str) -> bool:
    if s.count("=") > 1:
        return True
    if re.search(r"[∫∑√±≤≥≈∞∂]", s) and len(s) > 10:
        return True
    return False


def section_at(handout: dict, page: int) -> dict:
    """The section a reader at the top of `page` is in.

    The first heading printed on that page wins; otherwise the last heading
    before it.  This keeps "current section" honest when a page starts a new
    section halfway through.
    """
    items = handout.get("outline") or []
    for item in items:
        if item["page"] == page:
            return item
    best = None
    for item in items:
        if item["page"] < page:
            best = item
        else:
            break
    return best or {"page": 1, "title": "开头", "level": 1}


# --------------------------------------------------------------------------
# retrieval
# --------------------------------------------------------------------------

_NORM_DROP = re.compile(r"[\s\u3000,，.。;；:：、!！?？'\"“”‘’()（）\[\]【】<>《》\-—_~`|/\\]")


def _norm(s: str) -> str:
    return _NORM_DROP.sub("", s or "").lower()


def locate(handout: dict, text: str) -> dict:
    """Find the page a pasted selection came from.  Returns {page, score}."""
    needle = _norm(text)
    if not handout or not needle:
        return {"page": None, "score": 0.0}
    best = {"page": None, "score": 0.0}
    probe = needle[:80]
    for p in handout["pages"]:
        hay = _norm(p["text"])
        if not hay:
            continue
        if probe and probe in hay:
            return {"page": p["n"], "score": 1.0}
    # fall back to 3-gram overlap
    grams = {needle[i : i + 3] for i in range(0, max(1, len(needle) - 2))}
    if not grams:
        return best
    for p in handout["pages"]:
        hay = _norm(p["text"])
        if not hay:
            continue
        hit = sum(1 for g in grams if g in hay)
        score = hit / len(grams)
        if score > best["score"]:
            best = {"page": p["n"], "score": round(score, 3)}
    return best


_CONCEPT = re.compile(
    r"(定义|定理|引理|推论|命题|性质|法则|公式|不等式|注意|易错|例题|例\s*\d|"
    r"设\s|若\s|则\s|证明|结论|注\s*\d|Remark|Theorem|Lemma|Definition)"
)
_NUMBERED = re.compile(
    r"^\s*(定义|定理|引理|推论|命题|例|注)\s*[\d一二三四五六七八九十]"
)


def key_points(pages: list, upto_page: int, limit_chars: int = 3000) -> str:
    """A compact list of statements already covered (pages <= upto_page)."""
    picked = []
    for p in pages:
        if p["n"] > upto_page:
            break
        for line in p["text"].split("\n"):
            s = line.strip()
            if not s or len(s) < 4:
                continue
            if _NUMBERED.match(s) or (_CONCEPT.search(s) and len(s) <= 140):
                if len(s) <= 140:
                    picked.append("P%d · %s" % (p["n"], s))
    if not picked:
        # no recognisable statements: fall back to the first sentence of each page
        for p in pages:
            if p["n"] > upto_page:
                break
            first = next((x.strip() for x in p["text"].split("\n") if len(x.strip()) > 6), "")
            if first:
                picked.append("P%d · %s" % (p["n"], first[:120]))
    # keep the most recent material when over budget
    out, total = [], 0
    for item in reversed(picked):
        if total + len(item) + 1 > limit_chars:
            break
        out.append(item)
        total += len(item) + 1
    out.reverse()
    return "\n".join(out)


def page_text(handout: dict, page: int) -> str:
    for p in handout["pages"]:
        if p["n"] == page:
            return p["text"]
    return ""


def toc_lines(handout: dict, after_page: int | None = None) -> str:
    items = handout.get("outline") or []
    if after_page is not None:
        items = [i for i in items if i["page"] > after_page]
    return "\n".join(
        "%s第%d页 · %s" % ("  " * max(0, i["level"] - 1), i["page"], i["title"])
        for i in items
    )


def clip(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n……（后文已省略）"


def load_handout(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def save_handout(handout: dict, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(handout, fh, ensure_ascii=False)
    os.replace(tmp, path)
