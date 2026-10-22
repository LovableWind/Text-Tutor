# -*- coding: utf-8 -*-
"""Deterministic scope guard: does an answer cite material past the current page?

The model is asked to keep every forward reference inside a ⏭ line.  This module
checks that claim mechanically, so the server can run one cheap repair pass when
the answer slips.
"""

from __future__ import annotations

import re

import llm

PAGE_RE = re.compile(r"第\s*(\d+)\s*页")
SECT_RE = re.compile(r"(\d+\.\d+)\s*节")


def _flags(text: str) -> list:
    """True for lines that belong to a ⏭/➕ callout block."""
    mask = []
    inside = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(("⏭", "➕")):
            inside = True
        elif not s:
            inside = False
        mask.append(inside)
    return mask


def _section_pages(handout: dict) -> dict:
    out = {}
    for item in handout.get("outline") or []:
        m = re.match(r"(\d+\.\d+)", item.get("title") or "")
        if m:
            out[m.group(1)] = item.get("page")
    return out


def check_scope(answer: str, page: int, handout: dict | None) -> list:
    """Return human-readable violations of the 'no forward citations in prose' rule."""
    if not answer or not handout:
        return []
    lines = answer.split("\n")
    mask = _flags(answer)
    plain = "\n".join(l for l, f in zip(lines, mask) if not f)
    issues = []
    for m in PAGE_RE.finditer(plain):
        n = int(m.group(1))
        if n > page and n <= (handout.get("page_count") or 10**6):
            issues.append("正文引用了第%d页" % n)
    sections = _section_pages(handout)
    for m in SECT_RE.finditer(plain):
        p = sections.get(m.group(1))
        if p and p > page:
            issues.append("正文引用了 %s 节（第%d页）" % (m.group(1), p))
    # keep the list short and stable
    seen, out = set(), []
    for item in issues:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:4]


REPAIR_INSTRUCTION = """你刚才的回答里，正文出现了当前页之后的页码或小节号：{issues}。

请把这份回答重写一遍，只做一件事：把涉及后文的句子改成以 ⏭ 开头的一行（格式与规则里一致），
其余句子原样保留，不要增删内容、不要换说法、不要重新推导。

直接输出重写后的完整回答。"""


def repair(settings, system, messages, answer, issues, page, handout):
    """Ask the model to fix only the stray forward references.

    Returns the rewritten answer, or None when the rewrite looks unsafe (too
    short, missing structure) or still violates the rule.
    """
    if not issues:
        return None
    local = dict(settings)
    local["temperature"] = 0
    local["max_tokens"] = min(2600, max(700, int(len(answer) * 1.2)))
    follow = [
        {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        {"role": "user", "content": [{"type": "text", "text": REPAIR_INSTRUCTION.format(issues="；".join(issues))}]},
    ]
    try:
        result = llm.stream_chat(local, system, list(messages) + follow)
        text = (result.text or "").strip()
    except Exception:
        return None
    if len(text) < 0.6 * len(answer):
        return None
    if not text.startswith("**"):
        return None
    if check_scope(text, page, handout):
        return None
    return text
