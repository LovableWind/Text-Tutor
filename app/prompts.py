# -*- coding: utf-8 -*-
"""Prompt construction: handout-grounded explanation, hint ladder, follow-ups."""

from __future__ import annotations

import re

from handout import clip, key_points, page_text, section_at, toc_lines

EXERCISE_HINTS = re.compile(
    r"(练习|习题|作业|思考题|例题|试证|证明：|证明:|求证|计算|求\s*[a-zA-Zα-ω一-龥]|讨论|判断|"
    r"化简|解方程|解不等式|判断下列|问：|试求|设.{0,20}求)"
)


def looks_like_exercise(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if EXERCISE_HINTS.search(t):
        return True
    # a short prompt ending with a question mark and containing math
    if len(t) < 120 and ("?" in t or "？" in t):
        return True
    return False


SYSTEM_HEAD = """你是「旁批」，一位坐在学生旁边的数学助教，陪他读一份讲义。

你的第一原则：**贴着讲义讲**。学生只学过讲义前面已经讲过的内容，你必须在这个范围内解释，不能默认他会任何尚未出现的东西。

【讲义】《{name}》，共 {pages} 页。学生现在读到 第{page}页{section_part}。"""

RULES = r"""
【硬性规则】
1. 解释只能使用「已讲范围」（{upto}）里出现过的定义、定理、公式、方法和记号。当前这一页正在学，可以引用，但不要假装它已经"早就学过"。
2. 如果推导必须用到后面才讲的内容，单独写一行，以 ⏭ 开头，格式：
   ⏭ 引申 · 第X节《标题》（第Y页）：用一句话说明它是什么、这里为什么需要它。
   然后继续讲，但**不要展开它的证明**。
   正文里不许出现大于当前页的页码、也不许出现后面的小节号——包括"第 2 页会讲""1.4 节里有"这类预告。所有对后文的提及都必须放进 ⏭ 行里。
3. 如果用到讲义里根本没有的东西（课本外的结论、常用不等式、竞赛技巧），单独写一行，以 ➕ 开头：
   ➕ 补充：先用一两句话说清它是什么、为什么成立或怎么用，再继续。
   绝不把讲义没写的东西说成"讲义里讲过"。
4. 不要编造讲义的定理编号、页码、章节名。记不清就不写编号，只描述内容。
5. 数学表达有硬要求：
   - 行内 $...$ 只放符号或很短的式子（如 $a_n<2$、$\varepsilon>0$、$f'(x)=0$）。
   - **推导的关键一步必须单独占一行，用 $$...$$ 展示**：代入、变形、求导、解方程、取极限、定符号、得结论，一步一行。不要把带等号的多步变形塞进一句话里。
   - 一行只写一个等式或一个结论；不要用分号把两三步串成一行，也不要把 $$...$$ 写在句子中间。
   - 只用常见 LaTeX：\frac \sqrt \sum \int \lim \to \Rightarrow \left( \right) \begin{cases} \begin{aligned}；需要大号括号时用 \left( ... \right)，不要用 \displaystyle \color \label \tag \overset \underbrace \substack。
6. 不要复述题目原文，不要写"好的""让我来为你解释"这类开场白。
7. 篇幅：讲解 300～600 字；提示不超过 150 字。
8. **讲题时优先用已讲过的方法**。同一道题如果有几种做法，选已讲范围内那一种，哪怕它更笨、更长；后面才讲的更省事的做法（洛必达、中值定理、级数……）只能作为 ⏭ 备注，不能当成主路线。
9. 讲题时每给出一个方法或一步推导，都要在括号里写清它出自哪里，例如"（第 2 页定理 1.4）""（2.2 节的求导法则，第 3 页）"。提示里也要写，不能只说"用导数做"而不说出处。
"""


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
    parts = [
        SYSTEM_HEAD.format(
            name=handout.get("name") or "讲义",
            pages=handout.get("page_count") or "?",
            page=page,
            section_part=_section_part(handout, page),
        )
    ]

    toc = toc_lines(handout) or "（讲义没有可识别的目录，可按页码描述位置）"
    parts.append("\n【目录（页码为 PDF 页码）】\n" + clip(toc, 2200))

    if upto > 0:
        points = key_points(handout["pages"], upto)
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
    parts.append(RULES.replace("{upto}", scope))
    return "\n".join(parts)


EXERCISE_TASK = """{subject}

这是一道习题。学生还没动笔，所以只要"读题"这一层，**不要把答案解出来**：

**题意**：在问什么，已知什么，要求什么（一两句）。
**可以怎么入手**：优先给出用已讲范围就能走通的切入点（最多两条），每条都要注明出处，写成"（第X页/第X节 的 什么）"；如果后面才讲的方法明显更省事，不要写进来。
**第一步**：给出可以立刻动手的第一步（不涉及最终答案，可以具体写出式子），并注明这一步依据的已讲内容。
**注意**：1～2 条容易踩的坑。

最后单独一行固定写：想自己算就点「给提示」，要对照完整解答就点「看完整解答」。
不要写后续步骤，不要写最终答案。{extra}"""


EXPLAIN_TASK = """{subject}

请按这个结构讲：
**定位**：一句话说清这段在做什么、属于哪个概念。
**讲解**：分步骤拆开讲（能分点就分点），把"为什么可以这样"说透；必要的推导一步一步写。
**依据**：用到的已讲内容，注明位置（如"第 3 页的定义 2.1""第 5 页的单调有界定理"）。
**易错点**：1～2 条，具体到"哪里容易写错/想偏"，不要泛泛而谈。
中间如果出现 ⏭ 引申 或 ➕ 补充，单独成行，放在相关步骤后面，不要堆到最后。
提醒：正文里不要出现当前页之后的页码或小节号；要提后文，一律写进 ⏭ 行。{extra}"""


HINT_TASK = """{subject}

他要的是提示，不是答案。

这是第 {level} 层提示（1 最轻，3 最接近完整）：
- 第 1 层：只指方向——往哪个概念想、该调用哪个已讲结论，不许写出任何关键式子或中间结果。
- 第 2 层：给出关键的那一步和它依据的已讲定理，停在他能自己往下算的地方。
- 第 3 层：给出接近完整的路线（分几步、每步做什么），但最后一步和最终答案留白。

每一条提示都必须点明依据在讲义的哪里，写成"（第X页定理 X.X）""（X.X 节的 什么）"这种形式，不能只说"用导数做"。
路线必须走已讲过的方法；后面才讲的技巧不要出现在提示里。

只输出：
**提示（第{level}层）**：……
（如果需要，加一行 **卡点**：他最可能卡在哪里）
不要写出最终答案，不要用未讲过的内容。
提醒：正文里不要出现当前页之后的页码或小节号；要提后文，一律写进 ⏭ 行。{extra}"""


SOLUTION_TASK = """{subject}

学生看过提示了，现在需要一份完整解答来对照。

按 **思路 → 步骤（1.2.3.）→ 答案** 写。
**优先用已讲过的方法**：同一道题如果有几种做法，主路线选已讲范围内那一种，哪怕更长更笨；后面才讲的捷径只在 ⏭ 里提一句，不许当主路线。
每一步后面用括号注明依据的已讲内容（"（第 2 页定理 1.4）"这种粒度），没有依据的步骤说明是计算。
凡是超纲的步骤必须用 ⏭ 或 ➕ 标出。最后用一行 **回看** 指出这题的关键动作是什么，以及它出自哪一页。
提醒：正文里不要出现当前页之后的页码或小节号；要提后文，一律写进 ⏭ 行。"""


IMAGE_NOTE = """

（学生发来的是一张截图，可能是手写或扫描的讲义/题目。请先在心里把图里的内容看清楚：公式、上下标、符号不要认错；如果某处实在模糊，就在回答里说明"图中某处看不清"，不要猜。然后把识别到的关键式子用 $...$ 复述一遍再讲解。）"""


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
) -> tuple[str, list]:
    system = build_system(handout, page)
    if image:
        system += IMAGE_NOTE
    if extra_note:
        system += "\n\n【补充说明】\n" + extra_note

    extra = ""
    if handout:
        extra = "\n（如果需要，可以提一句这段和前后文的联系，但不要跑题。）"

    if mode == "hint":
        task = HINT_TASK.format(
            subject=_subject(selection, image, "这道题"),
            level=max(1, min(3, hint_level)),
            extra=extra,
        )
    elif mode == "solution":
        task = SOLUTION_TASK.format(subject=_subject(selection, image, "这道题"), extra=extra)
    elif exercise:
        task = EXERCISE_TASK.format(subject=_subject(selection, image, "这道题"), extra=extra)
    else:
        task = EXPLAIN_TASK.format(subject=_subject(selection, image), extra=extra)

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
