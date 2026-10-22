# -*- coding: utf-8 -*-
"""Spot text that was almost certainly a formula before the PDF text layer ate it.

Copying a formula out of a typeset PDF usually loses superscripts, radicals and
fraction bars: ``∫₀¹ x² dx`` arrives as ``∫x2dx`` or ``f(x)dx = F(b) F(a)``.
The renderer cannot fix that, but the prompt can stop the model from confidently
deriving on a wrong expression, and the UI can nudge the user to snip instead.
"""

from __future__ import annotations

import re

STRONG = set("∫∬∭∑∏√∂∞→←↔⇒⇔≤≥≠≈∈∉⊂⊆∪∩")
OPS = set("=<>±×÷^_+-*/")
CJK = re.compile(r"[\u4e00-\u9fff]")

# multi-letter tokens that only show up in formulas
FUNC_TOKENS = (
    "lim", "sin", "cos", "tan", "cot", "ln", "log", "exp", "max", "min",
    "dx", "dy", "dt", "sqrt", "frac", "sum", "int", "prod", "partial",
)
LATEX_HINTS = ("\\frac", "\\sqrt", "\\int", "\\sum", "\\lim", "\\partial", "\\cdot", "\\times")


def looks_like_formula(text: str) -> bool:
    """True when the selection is more like a mangled formula than prose."""
    t = (text or "").strip()
    if len(t) < 3 or len(t) > 500:
        return False

    cjk = len(CJK.findall(t))
    # 五个以上汉字：这是题干、定理陈述或推理句，里面夹着公式，
    # 不是"被复制坏的公式"。复制坏掉的公式几乎不含中文。
    if cjk >= 5:
        return False

    strong = sum(1 for ch in t if ch in STRONG)
    ops = sum(1 for ch in t if ch in OPS)
    tokens = sum(1 for tok in FUNC_TOKENS if tok in t)
    hints = sum(1 for h in LATEX_HINTS if h in t)

    if strong >= 1 and len(t) <= 160:
        return True

    score = ops + tokens * 2 + hints * 4 + (1 if "=" in t else 0)
    return score >= 4
