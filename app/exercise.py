# -*- coding: utf-8 -*-
"""Is this selection a problem to solve, or a statement to understand?

Keywords alone are useless: "设 a_n=…，证明…" is obviously an exercise but
contains neither 习题 nor Exercise.  So we score structure first (imperatives,
question forms, option lists, blanks, numbering) and only ask the model when the
score lands in the ambiguous band.  When in doubt we lean towards "exercise":
asking costs one click, spoiling costs the exercise.
"""

from __future__ import annotations

import re

TASK_VERBS_ZH = (
    "证明", "求证", "试证", "求", "计算", "讨论", "判断", "化简", "解出", "求解",
    "验证", "确定", "找出", "说明", "分析", "估计", "比较", "构造", "举例",
    "举出反例", "展开", "化简", "检验", "推导", "试求", "试论", "论述", "简述",
    "阐述", "评价", "谈谈", "整理", "改写", "代入", "配成", "拆成", "求值", "作图", "画图",
    "阅读", "回答", "结合材料", "根据材料",
)
TASK_VERBS_EN = (
    "show that", "prove", "compute", "calculate", "find", "determine", "evaluate",
    "derive", "verify", "discuss", "solve", "construct", "give an example",
    "explain why", "show", "let ",
)

# “证明 对任意 ε>0…” 这类是解答过程，不是题目；但优先按题处理也无妨
STATEMENT_HEADS = ("定理", "定义", "引理", "推论", "命题", "性质", "法则", "公式")
STATEMENT_TAIL = ("必有", "则称", "称为", "记为", "当且仅当", "成立")

OPTION_RE = re.compile(r"[（(]\s*[A-D]\s*[)）]|[A-D][.、]\s*\S")
BLANK_RE = re.compile(r"[_＿]{2,}|\(\s*\)|（\s*）")
NUMBERED_RE = re.compile(r"^\s*(?:[（(]?\d{1,2}[).、．]|[①②③④⑤⑥⑦⑧⑨⑩])")
QUESTION_END = re.compile(r"[？?]\s*$")

KEYWORD_RE = re.compile(
    r"(习题|练习|作业|思考题|例题|试证|求证|习题|"
    r"(?:supplement(?:al)?\s+)?(?:exercise|problem|question|homework|practice)\s*[\d(（])",
    re.I,
)


def score(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    head = t[:40]
    total = 0

    if KEYWORD_RE.search(t):
        total += 4

    if any(v in head for v in TASK_VERBS_ZH):
        total += 3
    elif any(v in t for v in TASK_VERBS_ZH):
        total += 1

    low = t.lower()
    if any(v in low for v in TASK_VERBS_EN):
        total += 3

    if QUESTION_END.search(t):
        total += 1
        # 带问号的“为什么/是什么/含义/区别”是在求解释，不是在求解答
        if re.search(r"(是什么|为什么|为何|含义|意义|区别|关系|怎么理解|如何理解)", t):
            total -= 2
    if OPTION_RE.search(t):
        total += 3
    if BLANK_RE.search(t):
        total += 3
    if NUMBERED_RE.match(t):
        total += 1
    if re.search(r"设.{0,60}?[，,]\s*(?:求|证明|讨论|判断)", t):
        total += 2
    if re.search(r"已知.{0,60}?[，,]\s*(?:求|证明|讨论|判断)", t):
        total += 2

    # “证明过程/证明中/证明的”是在讲解答，不是在出题
    if re.search(r"证明(过程|中|的|思路|里)", t):
        total -= 4

    # 陈述句：定理/定义 + “则称/必有” 这类
    if any(t.startswith(w) for w in STATEMENT_HEADS):
        total -= 4
    elif any(w in t for w in STATEMENT_TAIL) and "？" not in t and "?" not in t:
        total -= 2

    if len(t) > 300:
        total -= 2
    return total


def judge(text: str) -> str:
    """Return 'exercise', 'prose' or 'ambiguous'."""
    s = score(text)
    if s >= 3:
        return "exercise"
    if s <= 0:
        return "prose"
    return "ambiguous"


def looks_like_exercise(text: str) -> bool:
    return judge(text) == "exercise"
