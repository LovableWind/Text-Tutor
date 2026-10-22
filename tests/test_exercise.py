# -*- coding: utf-8 -*-
"""Structural exercise detection: no keyword required."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))

from exercise import judge, score  # noqa: E402

CASES = [
    # 没有“习题”二字，但明显是题
    ("设 a_n = 1 + 1/2 + … + 1/n，证明 {a_n} 发散。", "exercise"),
    ("求极限 lim (sin x)/x", "exercise"),
    ("计算 ∫_0^1 x^2 dx", "exercise"),
    ("讨论 f(x)=x^3-3x 在 [-2,2] 上的单调性", "exercise"),
    ("已知 f(x)=x^2，求 f'(1)。", "exercise"),
    ("判断下列级数是否收敛：(A) ∑1/n (B) ∑1/n^2", "exercise"),
    ("证明：若 A 可逆，则 det(A^-1) = 1/det A。", "exercise"),
    ("1. 求下列函数的导数：y = x^3", "exercise"),
    ("填表：函数 f(x)=x^2 在 x=1 处的导数是 ____。", "exercise"),
    ("Which of the following is true? (A) … (B) …", "exercise"),
    ("Show that the sequence is bounded.", "exercise"),
    # 陈述句，不该问
    ("定理 1.4 单调有界数列必有极限。", "prose"),
    ("定义 1.1 设 {a_n} 是一个数列，A 是常数，若……则称数列收敛于 A。", "prose"),
    ("这一节讲的是导数的定义和几何意义。", "prose"),
    ("若 A 可逆，则 det(A^-1) = 1/det A。", "prose"),
    ("孔子认为，仁是礼的内在依据，礼是仁的外在表现。", "prose"),
    ("柏拉图认为，可感事物分有理念，理念才是真正的存在。", "prose"),
    ("所以 f(x)=0 时取到极小值。", "prose"),
    # 带“例”的题目仍然算题
    ("例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明收敛并求极限。", "exercise"),
    # 关键词仍然有效
    ("习题 2.1 求下列函数的单调区间", "exercise"),
    ("Exercise 3.2 Show that the sequence is bounded.", "exercise"),
    ("Supplement Exercise 2", "exercise"),
    ("论述题：试论孔子仁学与礼的关系", "exercise"),
]

passed, failed = 0, []
for text, want in CASES:
    got = judge(text)
    if got == want:
        passed += 1
    else:
        failed.append("%r -> %s (score %d, want %s)" % (text[:40], got, score(text), want))

# 灰色地带必须存在，否则模型兜底永远不会被触发
ambiguous = [t for t in ["证明过程的第二步是取 N", "请解释一下这个式子的含义"] if judge(t) == "ambiguous"]
passed += len(ambiguous)

print("%d passed, %d failed" % (passed, len(failed)))
for item in failed:
    print("  FAIL", item)
sys.exit(0 if not failed else 1)
