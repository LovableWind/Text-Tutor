# -*- coding: utf-8 -*-
"""A course corpus: an ordered list of decks (pptx/pdf) plus a reading position.

Reading position is (doc index, page).  "What has been covered" is therefore:
every page of the earlier decks, plus the earlier pages of the current deck.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import handout as handout_mod
import ppttext
import pptxtext

SUFFIX = re.compile(r"\.(pptx|ppt|pdf)$", re.I)
CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(text: str) -> int | None:
    """一小段中文数字 → 整数（只处理 1–999，够用于讲次序号）。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total, section, number = 0, 0, 0
    for ch in text:
        if ch in CN_DIGITS:
            number = CN_DIGITS[ch]
        elif ch == "十":
            section += (number or 1) * 10
            number = 0
        elif ch == "百":
            section += (number or 1) * 100
            number = 0
        else:
            return None
    return total + section + number


CN_NUMBER = r"[0-9零〇一二三四五六七八九十百两]+"

# 序号的几种常见写法，按优先级排列；取第一个命中的
_ORDINAL_PATTERNS = [
    # 第1讲 / 第一讲 / 第 3 章 / 第二节课
    re.compile(r"第\s*(" + CN_NUMBER + r")\s*(?:讲|课|章|节|次|回|单元|部分)"),
    # Lecture 3 / LECTURE_01 / LECTER-07 / Chapter 1 / Ch.2 / Unit 4 / Week 5
    re.compile(
        r"(?:lec\w*|lesson|class|chapter|chap|ch|unit|part|week|day|module|topic|deck|slide)"
        r"\s*[._\-\s]*?(\d{1,3})(?!\d)",
        re.I,
    ),
    # 3讲 / 12 课（数字在前、量词在后）
    re.compile(r"(?<!\d)(\d{1,3})\s*(?:讲|课|章|节|次)"),
    # 一 绪论 / 二、极限 / 1_导论 / 01. 概述（裸序号 + 分隔符）
    re.compile(r"^\s*(" + CN_NUMBER + r")\s*[\s._\-、,，:：·]"),
]


def ordinal_of(name: str) -> int | None:
    """Extract the lecture number from a file name, or None."""
    base = SUFFIX.sub("", os.path.basename(name or ""))
    for pattern in _ORDINAL_PATTERNS:
        m = pattern.search(base)
        if not m:
            continue
        value = cn_number(m.group(1))
        if value is not None and value > 0:
            return value
    return None


def _chunks(text: str):
    parts = re.split(r"(\d+)", text)
    return [(0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts if p != ""]


def natural_key(name: str):
    """Sort decks by lecture number; unnumbered files go last, then by name."""
    base = SUFFIX.sub("", os.path.basename(name or ""))
    number = ordinal_of(base)
    if number is not None:
        return (0, number, _chunks(base))
    return (1, 0, _chunks(base))


def build_doc(name: str, data: bytes) -> dict:
    lower = name.lower()
    if lower.endswith(".pdf"):
        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".corpus-tmp.pdf")
        with open(tmp, "wb") as fh:
            fh.write(data)
        try:
            record = handout_mod.build_handout(tmp, name)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        pages = record["pages"]
        quality = record["quality"]
        domain = record.get("domain") or "math"
    elif lower.endswith(".pptx"):
        pages = pptxtext.extract_pages(data)
        quality = "text" if sum(len(p["text"]) for p in pages) > 40 else "poor"
        domain = handout_mod.detect_domain(pages)
    elif lower.endswith(".ppt"):
        pages = ppttext.extract_pages(data)
        quality = "text" if sum(len(p["text"]) for p in pages) > 40 else "poor"
        domain = handout_mod.detect_domain(pages)
    else:
        raise pptxtext.PptxError("只支持 .pptx / .ppt / .pdf")

    pages = [{"n": int(p["n"]), "text": (p.get("text") or "").strip()} for p in pages]
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "ordinal": ordinal_of(name),
        "kind": "ppt" if lower.endswith(".ppt") else ("pptx" if lower.endswith(".pptx") else "pdf"),
        "domain": domain,
        "pages": pages,
        "outline": handout_mod.detect_outline(pages),
        "quality": quality,
    }


def new_corpus() -> dict:
    return {"docs": [], "created": time.time()}


def sort_docs(docs: list) -> list:
    return sorted(docs, key=lambda d: natural_key(d.get("name") or ""))


def page_count(doc: dict) -> int:
    return len(doc.get("pages") or [])


def locate(corpus: dict, text: str) -> dict:
    """Find which deck/page a pasted selection came from."""
    best = {"doc": None, "page": None, "score": 0.0}
    for idx, doc in enumerate(corpus.get("docs") or []):
        found = handout_mod.locate({"pages": doc.get("pages") or []}, text)
        if found.get("score", 0) > best["score"]:
            best = {"doc": idx, "page": found.get("page"), "score": found.get("score", 0.0)}
    return best


def section_at(doc: dict, page: int) -> dict:
    return handout_mod.section_at({"outline": doc.get("outline") or []}, page)


def _titles(doc: dict, limit: int = 6) -> str:
    items = doc.get("outline") or []
    # the title slide repeats the deck name; skip it
    if items and items[0]["page"] == 1 and SUFFIX.sub("", doc.get("name") or "") in items[0]["title"]:
        items = items[1:]
    names = [i["title"] for i in items]
    if not names:
        first = next((ln.strip() for ln in (doc["pages"][0]["text"].split("\n") if doc.get("pages") else []) if ln.strip()), "")
        return first[:40]
    text = "；".join(names[:limit])
    if len(names) > limit:
        text += "…"
    return text


def describe(corpus: dict, current: int) -> str:
    """One line per deck for the system prompt."""
    lines = []
    for idx, doc in enumerate(corpus.get("docs") or []):
        mark = "  ← 当前" if idx == current else ""
        lines.append("%d. %s（%d 页）%s%s" % (
            idx + 1, doc["name"], page_count(doc), _titles(doc, 5), mark))
    return "\n".join(lines)


def covered_points(corpus: dict, doc_idx: int, page: int, budget: int = 2600) -> str:
    """Key statements from every earlier deck, plus this deck's earlier pages."""
    docs = corpus.get("docs") or []
    chunks = []
    # earlier decks: a compact digest each, newest first until the budget is used
    per_doc = max(200, budget // max(1, doc_idx + 1))
    for idx in range(doc_idx):
        doc = docs[idx]
        points = handout_mod.key_points(doc["pages"], page_count(doc))
        if points:
            chunks.append("【%s】\n%s" % (doc["name"], handout_mod.clip(points, per_doc)))
    if doc_idx < len(docs):
        cur_points = handout_mod.key_points(docs[doc_idx]["pages"], page - 1)
        if cur_points:
            chunks.append("【本讲前面】\n%s" % handout_mod.clip(cur_points, max(600, budget // 2)))
    text = "\n".join(chunks)
    return handout_mod.clip(text, budget)


def ahead_outline(corpus: dict, doc_idx: int, page: int) -> str:
    """Titles that come after the current position (for ⏭ citations only)."""
    docs = corpus.get("docs") or []
    lines = []
    for idx in range(doc_idx, len(docs)):
        doc = docs[idx]
        for item in doc.get("outline") or []:
            if idx == doc_idx and item["page"] <= page:
                continue
            prefix = "" if idx == doc_idx else "（%s）" % doc["name"]
            lines.append("%s第%d页 · %s" % (prefix, item["page"], item["title"]))
    return handout_mod.clip("\n".join(lines), 1200)


def context(corpus: dict, doc_idx: int, page: int) -> dict:
    docs = corpus.get("docs") or []
    doc_idx = max(0, min(doc_idx, len(docs) - 1))
    doc = docs[doc_idx] if docs else {"name": "课件", "pages": [], "outline": []}
    page = max(1, min(page, max(1, page_count(doc))))
    sec = section_at(doc, page)
    return {
        "name": doc.get("name") or "课件",
        "domain": doc.get("domain") or "math",
        "doc_index": doc_idx,
        "doc_total": len(docs),
        "page": page,
        "page_count": page_count(doc),
        "section": sec.get("title") if sec else "",
        "structure": describe(corpus, doc_idx),
        "covered": covered_points(corpus, doc_idx, page),
        "prev": handout_mod.clip(handout_mod.page_text({"pages": doc.get("pages") or []}, page - 1), 1400),
        "current": handout_mod.clip(handout_mod.page_text({"pages": doc.get("pages") or []}, page), 2000),
        "ahead": ahead_outline(corpus, doc_idx, page),
        "covered_label": _covered_label(corpus, doc_idx, page),
    }


def _covered_label(corpus: dict, doc_idx: int, page: int) -> str:
    docs = corpus.get("docs") or []
    if doc_idx == 0 and page <= 1:
        return "还没有讲过任何内容（这是第一讲的第一页）"
    parts = []
    if doc_idx > 0:
        parts.append("第 1–%d 讲全部" % doc_idx)
    if page > 1:
        parts.append("本讲第 1–%d 页" % (page - 1))
    return " + ".join(parts) if parts else "本讲之前的页"


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------


def save(corpus: dict, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False)
    os.replace(tmp, path)


def load(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and "docs" in data else None
    except Exception:
        return None


def summary(corpus: dict, doc_idx: int, page: int) -> dict:
    docs = corpus.get("docs") or []
    return {
        "docs": [
            {
                "id": d["id"],
                "name": d["name"],
                "kind": d.get("kind"),
                "ordinal": d.get("ordinal"),
                "domain": d.get("domain"),
                "pages": page_count(d),
                "quality": d.get("quality"),
                "outline": d.get("outline") or [],
            }
            for d in docs
        ],
        "position": {"doc": doc_idx, "page": page},
        "total_pages": sum(page_count(d) for d in docs),
    }
