# -*- coding: utf-8 -*-
"""Prompt construction: handout-grounded explanation, hint ladder, follow-ups."""

from __future__ import annotations

import re

from handout import clip, key_points, page_text, section_at, toc_lines
import exercise
import profiles

def looks_like_exercise(text: str) -> bool:
    """结构判断优先；真正难判的交给 exercise.judge / 模型分类器。"""
    return exercise.looks_like_exercise(text)


SYSTEM_HEAD = """你是「旁批」，{role}，陪他读一份讲义。

你的第一原则：**贴着讲义讲**。学生只学过讲义前面已经讲过的内容，你必须在这个范围内解释，不能默认他会任何尚未出现的东西。

【讲义】《{name}》，共 {pages} 页。学生现在读到 第{page}页{section_part}。"""

def _section_part(handout: dict, page: int) -> str:
    sec = section_at(handout, page)
    if not sec or sec.get("page") == 1 and sec.get("title") == "开头":
        return ""
    return "（%s）" % sec["title"]


def build_system(handout: dict | None, page: int) -> str:
    if not handout:
        return (
            "你是「旁批」，一位数学助教。学生没有上传讲义，所以你没有讲义上下文："
            "请用最标准、最基础的方式讲解。\n"
            "凡是用到超出大学低年级公共课范围（或明显超出这道题所在一章）的结论、技巧，"
            "单独写一行并以 ➕ 开头，先用一两句话把它讲清楚再继续。\n"
            "不要使用 ⏭（没有讲义可以引用页码）。\n"
            "行内公式用 $...$，中文讲解，句子短，不说客套话。"
        )
    page = max(1, min(page, handout.get("page_count") or 1))
    upto = page - 1
    domain = handout.get("domain") or "math"
    profile = profiles.get_profile(domain)
    parts = [
        SYSTEM_HEAD.format(
            role=profile["role"],
            name=handout.get("name") or "讲义",
            pages=handout.get("page_count") or "?",
            page=page,
            section_part=_section_part(handout, page),
        )
    ]

    toc = toc_lines(handout) or "（讲义没有可识别的目录，可按页码描述位置）"
    parts.append("\n【目录（页码为 PDF 页码）】\n" + clip(toc, 2200))

    if upto > 0:
        points = key_points(handout["pages"], upto, domain=domain)
        if points:
            parts.append("\n【已讲范围的关键结论（第 1 页—第 %d 页）】\n%s" % (upto, clip(points, 2600)))
    else:
        parts.append("\n【已讲范围】第 1 页之前没有内容：这是讲义的开头，几乎一切都还没讲。")

    prev_text = page_text(handout, page - 1)
    if prev_text:
        parts.append("\n【上一页原文（节选）】\n" + clip(prev_text, 1600))

    cur_text = page_text(handout, page)
    if cur_text:
        parts.append("\n【当前页原文（节选）】\n" + clip(cur_text, 2200))

    after = toc_lines(handout, after_page=page)
    if after:
        parts.append("\n【后续目录（只用于第 2 条规则的引用，不算已讲）】\n" + clip(after, 1200))

    scope = "第 1 页到第 %d 页" % upto if upto > 0 else "第 1 页之前（即还没有讲过任何内容）"
    parts.append(profile["rules"].replace("{upto}", scope))
    return "\n".join(parts)


EXERCISE_TASK = """{subject}

这是一道习题。学生还没动笔，所以只要"读题"这一层，**不要把答案解出来**：

**题意**：在问什么，已知什么，要求什么（一两句）。
**可以怎么入手**：优先给出用已讲范围就能走通的切入点（最多两条），每条都要注明出处，写成"（第X页/第X节 的 什么）"；如果后面才讲的方法明显更省事，不要写进来。
**第一步**：给出可以立刻动手的第一步（不涉及最终答案，可以具体写出式子），并注明这一步依据的已讲内容。
**注意**：1～2 条容易踩的坑。

最后单独一行固定写：想自己算就点「给提示」，要对照完整解答就点「看完整解答」。
不要写后续步骤，不要写最终答案。{extra}"""


TRANSLATE_TASK = """{subject}

学生只要翻译，不要讲解。

把这段内容译成通顺的中文：数学符号、公式、编号保持原样（公式用 $...$ 包住），不要改写题意，也不要补充任何原文没有的信息。

硬性要求：
- 不要解题、不要提示思路、不要给答案、不要补充背景知识。
- 如果原文本来就是中文，只回一句"原文是中文，无需翻译"，并把原文原样贴回。
- 如果里面有术语拿不准，在译文后用一行 **术语**：给出"英文 → 中文（可选译法）"。"""


IMAGE_NOTE = """

（学生发来的是一张截图，可能是手写或扫描的讲义/题目。请先在心里把图里的内容看清楚：公式、上下标、符号不要认错；如果某处实在模糊，就在回答里说明"图中某处看不清"，不要猜。然后把识别到的关键式子用 $...$ 复述一遍再讲解。）"""

TRANSLATE_NOTE = """

（本次只做翻译：不要讲解、不要提示思路、不要解题、不要补充背景。译文之外最多给一行术语对照。）"""

FORMULA_NOTE = r"""

（注意：学生这段文字是从 PDF 文字层复制来的，而公式的上下标、分式横线、根号、积分上下限在这种复制里几乎一定会丢失或错位——比如 $\int_0^1 x^2\,dx$ 复制出来会变成 "∫x2dx"。如果这个式子的含义不唯一，先用一句话说明"按你贴的这串，它应该是……（并给出你补全后的写法）"，再基于补全后的式子讲；不要拿错版的式子硬推。回答最后提醒一句：框选截图（Win+Shift+S）比直接复制更可靠。）"""


def _subject(selection: str, image: bytes | None, kind: str = "这段内容") -> str:
    sel = (selection or "").strip()
    if sel:
        return "学生选中了下面%s：\n\n<<<\n%s\n>>>" % (kind, sel)
    if image:
        return "学生发来一张截图（没有附文字），请先看图。"
    return "学生发来了一段空白内容。"


def build_messages(
    handout: dict | None,
    page: int,
    selection: str,
    mode: str = "explain",
    hint_level: int = 1,
    image: bytes | None = None,
    extra_note: str = "",
    exercise: bool = False,
    formula_suspect: bool = False,
) -> tuple[str, list]:
    system = build_system(handout, page)
    if mode == "translate":
        system += TRANSLATE_NOTE
    if image:
        system += IMAGE_NOTE
    elif formula_suspect:
        system += FORMULA_NOTE
    if extra_note:
        system += "\n\n【补充说明】\n" + extra_note

    domain = (handout or {}).get("domain") or "math"
    task = _task_text(selection, image, mode, hint_level, exercise, bool(handout), domain)

    content = []
    if image:
        content.append({"type": "image", "media_type": "image/png", "data": image})
    content.append({"type": "text", "text": task})
    return system, [{"role": "user", "content": content}]


def _task_text(selection, image, mode, hint_level, exercise, has_context, domain="math"):
    extra = ""
    if has_context:
        extra = "\n（如果需要，可以提一句这段和前后文的联系，但不要跑题。）"
    if mode == "translate":
        return TRANSLATE_TASK.format(subject=_subject(selection, image, "这段内容"))
    profile = profiles.get_profile(domain)
    subject = _subject(selection, image, "这道题" if mode in ("hint", "solution") else "这段内容")
    if mode == "hint":
        return profile["hint"].format(
            subject=subject,
            level=max(1, min(3, hint_level)),
            extra=extra,
        )
    if mode == "solution":
        return profile["solution"].format(subject=subject, extra=extra)
    # 习题默认不会走到这里（先弹三选一）；用户明确点了「讲解」就是真的要讲
    return profile["explain"].format(subject=subject, extra=extra)


MULTI_HEAD = """你是「旁批」，{role}，陪他读一整套课程课件。

你的第一原则：**贴着课件讲**。学生只学过「已讲范围」里出现过的内容，你必须在这个范围内解释，不能默认他会任何尚未出现的东西。

【课程】共 {doc_total} 份课件，当前是第 {doc_no} 份《{name}》，第 {page}/{page_count} 页{section_part}。"""

MULTI_EXTRA = """

（本课程有多份课件：已经讲过的包括前面各讲的全部内容和本讲前面的页。引用后面才讲的内容时，⏭ 行要写清讲次和页码，例如「⏭ 引申 · 第3讲《导数与微分》2.2 节（该讲第4页）」；不然后文的页码会产生歧义。）"""


def build_system_multi(ctx: dict) -> str:
    """System prompt for a multi-deck corpus (ctx comes from corpus.context())."""
    section_part = "（%s）" % ctx["section"] if ctx.get("section") else ""
    domain = ctx.get("domain") or "math"
    profile = profiles.get_profile(domain)
    parts = [MULTI_HEAD.format(
        role=profile["role"],
        doc_total=ctx.get("doc_total") or 1,
        doc_no=(ctx.get("doc_index") or 0) + 1,
        name=ctx.get("name") or "课件",
        page=ctx.get("page") or 1,
        page_count=ctx.get("page_count") or 1,
        section_part=section_part,
    )]

    if ctx.get("structure"):
        parts.append("\n【课程结构（按授课顺序）】\n" + ctx["structure"])

    parts.append("\n【已讲范围】" + (ctx.get("covered_label") or ""))

    if ctx.get("covered"):
        parts.append("\n【前面讲过什么】\n" + ctx["covered"])

    if ctx.get("prev"):
        parts.append("\n【本讲上一页原文（节选）】\n" + ctx["prev"])

    if ctx.get("current"):
        parts.append("\n【当前页原文（节选）】\n" + ctx["current"])

    if ctx.get("ahead"):
        parts.append("\n【后面会讲（只用于 ⏭ 引用，不算已讲）】\n" + ctx["ahead"])

    parts.append(profile["rules"].replace("{upto}", ctx.get("covered_label") or ""))
    parts.append(MULTI_EXTRA)
    return "\n".join(parts)


def build_messages_multi(
    ctx: dict,
    selection: str,
    mode: str = "explain",
    hint_level: int = 1,
    image: bytes | None = None,
    extra_note: str = "",
    exercise: bool = False,
    formula_suspect: bool = False,
) -> tuple[str, list]:
    system = build_system_multi(ctx)
    if mode == "translate":
        system += TRANSLATE_NOTE
    if image:
        system += IMAGE_NOTE
    elif formula_suspect:
        system += FORMULA_NOTE
    if extra_note:
        system += "\n\n【补充说明】\n" + extra_note

    task = _task_text(selection, image, mode, hint_level, exercise, True, ctx.get("domain") or "math")
    content = []
    if image:
        content.append({"type": "image", "media_type": "image/png", "data": image})
    content.append({"type": "text", "text": task})
    return system, [{"role": "user", "content": content}]


def build_chat_messages(
    handout: dict | None,
    page: int,
    card: dict,
) -> tuple[str, list]:
    system = build_system(handout, page)
    system += (
        "\n\n现在学生在追问。回答要短（一般不超过 250 字），直接回答他的问题；"
        "需要引用讲义时给出页码；仍然遵守上面三条关于「已讲 / ⏭ 引申 / ➕ 补充」的规则。"
    )
    history = []
    selection = (card.get("selection") or "").strip()
    answer = (card.get("answer") or "").strip()
    if selection:
        history.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": "我选中的内容是：\n<<<\n%s\n>>>" % clip(selection, 1200)}],
            }
        )
    if answer:
        history.append(
            {"role": "assistant", "content": [{"type": "text", "text": clip(answer, 3000)}]}
        )
    history.append(
        {"role": "user", "content": [{"type": "text", "text": card.get("question") or ""}]}
    )
    return system, history
