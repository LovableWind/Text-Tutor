# -*- coding: utf-8 -*-
"""Profile tests: maths and humanities prompts must stay independent."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

import handout as H  # noqa: E402
import prompts  # noqa: E402

passed, failed = 0, []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   " + name)
    else:
        failed.append(name)
        print("  FAIL " + name + " " + str(detail))


def main():
    math = H.build_handout(os.path.join(ROOT, "samples", "示例讲义.pdf"), "示例讲义")
    hum = H.build_handout(os.path.join(ROOT, "samples", "人文示例.pdf"), "人文示例")

    check("数学讲义判为 math", math["domain"] == "math", math["domain"])
    check("人文讲义判为 humanities", hum["domain"] == "humanities", hum["domain"])

    m_sys = prompts.build_system(math, 2)
    h_sys = prompts.build_system(hum, 2)

    # 数学这一套必须保持原样
    check("数学→数学助教", "一位数学助教" in m_sys)
    check("数学→保留 LaTeX 硬规矩", "数学表达有硬要求" in m_sys and "\\left( ... \\right)" in m_sys)
    check("数学→保留洛必达那条", "洛必达" in m_sys)
    check("数学→不出现人文措辞", "人文社科" not in m_sys and "引用讲义原文用「」" not in m_sys)

    # 人文这一套独立
    check("人文→人文社科助教", "一位人文社科助教" in h_sys)
    check("人文→引用规则", "引用讲义原文用「」" in h_sys)
    check("人文→禁止编造人名年代", "人名、著作名、年代" in h_sys)
    check("人文→不出现数学 LaTeX 规矩", "数学表达有硬要求" not in h_sys and "洛必达" not in h_sys)

    # 任务模板也分家
    m_task = prompts._task_text("定理 1.4", None, "explain", 1, False, True, "math")
    h_task = prompts._task_text("柏拉图认为", None, "explain", 1, False, True, "humanities")
    check("数学任务要求写推导", "推导一步一步写" in m_task)
    check("人文任务要求引用原文", "引用原文关键句" in h_task)
    check("人文任务不问属于哪个概念", "属于哪个概念" not in h_task)

    # 习题识别：两种学科都要认
    check("中文习题", prompts.looks_like_exercise("习题 2.1 求极限"))
    check("英文 Exercise", prompts.looks_like_exercise("Exercise 3.2 Show that ..."))
    check("英文 Supplement Exercise", prompts.looks_like_exercise("Supplement Exercise 2"))
    check("人文论述题", prompts.looks_like_exercise("论述题：试论孔子仁学与礼的关系"))
    check("人文材料题", prompts.looks_like_exercise("阅读下列材料，回答问题"))

    print("\n%d passed, %d failed" % (passed, len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
