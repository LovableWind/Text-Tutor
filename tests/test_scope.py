# -*- coding: utf-8 -*-
"""Offline boundary test: does the context really stop at the current page?

No model call, no API key.  It inspects the system prompt that /api/explain would
send and asserts that later pages contribute nothing but their table-of-contents
titles.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

import handout as H  # noqa: E402
import prompts  # noqa: E402

passed = 0
failed = []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed.append(name)
        print("  FAIL %s %s" % (name, detail))


def main():
    rec = H.build_handout(os.path.join(ROOT, "samples", "示例讲义.pdf"), "示例讲义")
    outline_titles = {i["title"] for i in rec["outline"]}

    for page in range(1, rec["page_count"] + 1):
        system = prompts.build_system(rec, page)
        current = H.page_text(rec, page)

        # 1. the header names the right page
        check("p%d: header names page" % page, ("第%d页" % page) in system)

        # 2. no body text from a later page leaks in (titles are allowed)
        leaks = []
        for later in range(page + 1, rec["page_count"] + 1):
            for line in H.page_text(rec, later).split("\n"):
                s = line.strip()
                if len(s) < 10:
                    continue
                if any(s == t or s in t for t in outline_titles):
                    continue
                if s in current:
                    continue
                if s in system:
                    leaks.append((later, s[:40]))
        check("p%d: no later-page body text" % page, not leaks, leaks[:3])

        # 3. the stated range is exactly 1..page-1
        if page == 1:
            check("p1: says nothing is covered yet", "第 1 页之前" in system)
            check("p1: no key points section", "关键结论" not in system)
        else:
            check("p%d: range is 1..%d" % (page, page - 1), ("第 1 页到第 %d 页" % (page - 1)) in system)
            points = H.key_points(rec["pages"], page - 1)
            if points:
                bad = [ln for ln in points.split("\n") if ln.startswith("P") and int(ln[1:].split(" ")[0]) >= page]
                check("p%d: key points only from earlier pages" % page, not bad, bad[:3])

        # 4. rules still present and parameterised
        check("p%d: rules mention the covered range" % page, "已讲范围" in system and "⏭" in system and "➕" in system)

    # 5. a page-2 prompt must not carry page 3's definition text
    system2 = prompts.build_system(rec, 2)
    check("p2: 导数的定义 body absent", "若极限" not in system2 and "在点 x_0 的某邻域内" not in system2)
    check("p2: later TOC title still visible", "2.1 导数的定义" in system2)

    print("\n%d passed, %d failed" % (passed, len(failed)))
    if failed:
        print("failed:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
