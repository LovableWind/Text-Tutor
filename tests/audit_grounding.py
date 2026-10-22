# -*- coding: utf-8 -*-
"""Live audit: does a real answer stay inside the pages already covered?

    $env:DSK = "sk-..."
    python tests/audit_grounding.py

Rules checked automatically
  A. no page citation > current page outside a ⏭/➕ line
  B. no section reference (e.g. "2.1 节") to a later section outside a ⏭ line
  C. every 定理/定义/例 number in the answer exists in the handout (no invented ids)
  D. a statement that exists only on a later page is cited only inside a ⏭ line
  E. terms that live only on later pages must come with a ⏭ line somewhere
  F. terms that never appear in the handout must come with a ➕ line somewhere
  G. every ⏭ line carries a page number or a section title from the TOC
"""

from __future__ import annotations

import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

import handout as H  # noqa: E402
import guard  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402

PAGE_RE = re.compile(r"第\s*(\d+)\s*页")
STMT_RE = re.compile(r"(定义|定理|引理|推论|命题|例)\s*(\d+(?:\.\d+)?)")
SECT_RE = re.compile(r"(\d+\.\d+)\s*节")

CASES = [
    {
        "name": "P1 定义1.1（完全在范围内）",
        "page": 1,
        "text": "定义 1.1 设 {a_n} 是一个数列，A 是一个常数。若对任意 ε>0，存在正整数 N，使得当 n>N 时恒有 |a_n - A| < ε，则称数列 {a_n} 收敛于 A。",
        "later": ["导数", "可导", "洛必达"],
        "outside": ["泰勒", "柯西"],
    },
    {
        "name": "P1 例1.1（用定义证明）",
        "page": 1,
        "text": "例 1.1 用定义证明 lim (n+1)/n = 1。",
        "later": ["洛必达", "导数"],
        "outside": ["泰勒"],
    },
    {
        "name": "P1 越界提问：洛必达",
        "page": 1,
        "text": "能不能用洛必达法则求 lim (sin x)/x ？",
        "later": ["导数", "可导"],
        "outside": ["洛必达"],
    },
    {
        "name": "P2 例1.2（单调有界应用）",
        "page": 2,
        "text": "例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。",
        "later": ["导数", "洛必达"],
        "outside": ["不动点", "压缩映射"],
    },
    {
        "name": "P2 两个重要极限",
        "page": 2,
        "text": "lim (1+1/n)^n = e",
        "later": ["导数"],
        "outside": ["对数", "自然对数", "ln"],
    },
    {
        "name": "P3 定义2.1（导数定义）",
        "page": 3,
        "text": "定义 2.1 设函数 y=f(x) 在点 x_0 的某邻域内有定义，若极限 lim [f(x_0+Δx) - f(x_0)]/Δx (Δx→0) 存在，则称 f 在 x_0 处可导。",
        "later": ["二阶导数", "莱布尼茨", "拉格朗日", "罗尔"],
        "outside": ["泰勒"],
    },
    {
        "name": "P4 拉格朗日中值定理",
        "page": 4,
        "text": "定理 2.4（拉格朗日中值定理）f(b)-f(a) = f'(ξ)(b-a)。",
        "later": [],
        "outside": ["柯西中值", "泰勒"],
    },
    {
        "name": "P4 习题2.1 读题（默认模式）",
        "page": 4,
        "text": "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
        "later": ["二阶导数", "莱布尼茨"],
        "outside": ["泰勒"],
        "exercise": True,
        "need_citation": True,
    },
    {
        "name": "P4 习题2.1 提示 L1",
        "page": 4,
        "text": "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
        "later": ["二阶导数", "莱布尼茨"],
        "outside": ["泰勒"],
        "mode": "hint",
        "level": 1,
        "need_citation": True,
    },
    {
        "name": "P4 习题2.1 提示 L3",
        "page": 4,
        "text": "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
        "later": ["二阶导数", "莱布尼茨"],
        "outside": ["泰勒"],
        "mode": "hint",
        "level": 3,
        "need_citation": True,
    },
    {
        "name": "P4 习题2.1 完整解答",
        "page": 4,
        "text": "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
        "later": ["二阶导数", "莱布尼茨"],
        "outside": ["泰勒"],
        "mode": "solution",
        "need_citation": True,
    },
]

DISCLAIMER = ("没有", "未讲", "不在", "不属于", "超纲", "尚未", "还没", "课本外", "讲义外", "没讲")


def build_index(rec):
    stmts = {}
    sections = {}
    for item in rec["outline"]:
        m = re.match(r"(\d+\.\d+)", item["title"])
        if m:
            sections[m.group(1)] = item["page"]
    for page in rec["pages"]:
        for m in STMT_RE.finditer(page["text"]):
            stmts["%s %s" % (m.group(1), m.group(2))] = page["n"]
    return stmts, sections


def split_flags(answer):
    """Return (lines, flagged_mask) where flagged lines sit inside ⏭/➕ blocks."""
    lines = answer.split("\n")
    mask = []
    in_flag = False
    for line in lines:
        s = line.strip()
        if s.startswith(("⏭", "➕")):
            in_flag = True
        elif not s:
            in_flag = False
        mask.append(in_flag)
    return lines, mask


def audit(answer, page, stmts, sections, case):
    v = []
    lines, mask = split_flags(answer)
    plain = "\n".join(l for l, f in zip(lines, mask) if not f)
    flagged = [l for l, f in zip(lines, mask) if f]
    has_later = any(l.strip().startswith("⏭") for l in flagged)
    has_extra = any(l.strip().startswith("➕") for l in flagged)

    for m in PAGE_RE.finditer(plain):
        if int(m.group(1)) > page:
            v.append("A 正文引用了后文页码：第%s页" % m.group(1))

    for m in SECT_RE.finditer(plain):
        p = sections.get(m.group(1))
        if p and p > page:
            v.append("B 正文引用了后文章节：%s 节（第%d页）" % (m.group(1), p))

    for m in STMT_RE.finditer(plain):
        key = "%s %s" % (m.group(1), m.group(2))
        if key not in stmts:
            v.append("C 编造了讲义里没有的编号：%s" % key)
        elif stmts[key] > page:
            v.append("D 正文引用了后文的 %s（第%d页）" % (key, stmts[key]))

    # I. a cited page and a cited statement in the same breath must agree
    for m in re.finditer(r"第\s*(\d+)\s*页", plain):
        cited_page = int(m.group(1))
        window = plain[m.end() : m.end() + 14]
        st = STMT_RE.search(window)
        if not st:
            continue
        key = "%s %s" % (st.group(1), st.group(2))
        if key in stmts and stmts[key] != cited_page and cited_page <= page:
            ctx = plain[max(0, m.start() - 12) : m.end() + 20].replace("\n", " ")
            v.append("I 页码与编号不符：写的是第%d页的 %s，实际在第%d页｜%s" % (cited_page, key, stmts[key], ctx))

    for term in case["later"]:
        if term in answer and not has_later:
            v.append("E 用了后文概念「%s」但没有 ⏭ 标注" % term)
    for term in case["outside"]:
        if term not in answer or has_extra:
            continue
        # naming an out-of-handout concept only to say "not covered yet" is fine
        exempt = False
        for m in re.finditer(re.escape(term), answer):
            window = answer[max(0, m.start() - 40) : m.end() + 40]
            if any(w in window for w in DISCLAIMER):
                exempt = True
                break
        if not exempt:
            v.append("F 用了讲义外概念「%s」但没有 ➕ 标注" % term)

    if case.get("need_citation"):
        cited = [int(m.group(1)) for m in PAGE_RE.finditer(answer)]
        cited_sections = [sections.get(m.group(1)) for m in SECT_RE.finditer(answer)]
        ok = any(p <= page for p in cited) or any(p and p <= page for p in cited_sections)
        if not ok:
            v.append("H 讲题时没有标明方法出自哪一页/哪一节")

    for line in flagged:
        if line.strip().startswith("⏭"):
            if not PAGE_RE.search(line) and not any(t in line for t in sections):
                v.append("G ⏭ 行缺少页码或章节：%s" % line.strip()[:40])
    return v, flagged


def main():
    key = os.environ.get("DSK", "")
    if not key:
        print("missing $env:DSK")
        return 2
    rec = H.build_handout(os.path.join(ROOT, "samples", "示例讲义.pdf"), "示例讲义")
    stmts, sections = build_index(rec)
    settings = {
        "protocol": "anthropic",
        "base_url": os.environ.get("DSH_BASE") or "https://api.deepseek.com/anthropic",
        "model": os.environ.get("DSH_MODEL") or "deepseek-flash",
        "api_key": key,
        "max_tokens": 1400,
        "temperature": 0.4,
        "thinking": os.environ.get("DSH_THINKING") or "disabled",
    }

    total = 0
    failures = 0
    for case in CASES:
        system, messages = prompts.build_messages(
            rec,
            case["page"],
            case["text"],
            mode=case.get("mode", "explain"),
            hint_level=case.get("level", 1),
            exercise=case.get("exercise", False),
        )
        t0 = time.time()
        try:
            res = llm.stream_chat(settings, system, messages)
            answer = res.text.strip()
        except Exception as exc:  # one flaky call should not kill the audit
            print("\n=== %s [ERROR] %.1fs %s" % (case["name"], time.time() - t0, exc))
            failures += 1
            total += 1
            continue
        problems, flagged = audit(answer, case["page"], stmts, sections, case)
        repaired = False
        if problems and os.environ.get("NO_REPAIR") != "1":
            fixed = guard.repair(settings, system, messages, answer, problems, case["page"], rec)
            if fixed:
                repaired = True
                answer = fixed
                problems, flagged = audit(answer, case["page"], stmts, sections, case)
        total += 1
        status = "PASS" if not problems else "FAIL"
        if problems:
            failures += 1
        print("\n=== %s [%s]%.1fs%s" % (
            case["name"], status, time.time() - t0, " · 自查修正过" if repaired else ""), flush=True)
        print("  标注行：")
        for line in flagged[:4]:
            print("    " + line.strip()[:110])
        if problems:
            for p in problems:
                print("  ! " + p)
        if os.environ.get("VERBOSE"):
            print(answer)

    print("\n%d/%d cases clean" % (total - failures, total))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
