# -*- coding: utf-8 -*-
"""Unit tests for app/formula.py (no API key, no network)."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))

from formula import looks_like_formula  # noqa: E402

FORMULAS = [
    "∫x2dx",
    "f(x)dx=F(b)-F(a)",
    "lim (n+1)/n = 1",
    "dy/dx = f'(x)",
    "x^2+y^2=1",
    "\\frac{a}{b}",
    "sqrt(2+a_n)",
    "面积 S=∫_0^1 f(x)dx",
    "∑_{k=1}^{n} k = n(n+1)/2",
    "A^-1 = adj(A)/det(A)",
    # 只有四个汉字的引导语 + 密集算子：仍按公式处理，警告一次不亏
    "若 A 可逆，则 det(A^-1) = 1/det A。",
]

PROSE = [
    "a=b",
    "a-b",
    "1+1=2",
    "求 f'(x)=0 的根",
    "定义 1.1 设 {a_n} 是数列，若对任意 ε>0 存在 N",
    "定理 1.4 单调有界数列必有极限。",
    "所以 f(x)=0 时取到极小值",
    "例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明收敛",
    "证明：对任意 ε>0，取 N=[1/ε]+1，当 n>N 时 |a_n−A|<ε。",
    "设函数 y=f(x) 在点 x_0 的某邻域内有定义，若极限存在则称可导。",
    "习题 2.1 讨论 f 在 [-2,2] 上的单调性与极值。",
]

passed = 0
failed = []

for text in FORMULAS:
    if looks_like_formula(text):
        passed += 1
    else:
        failed.append(("公式未识别", text))
for text in PROSE:
    if not looks_like_formula(text):
        passed += 1
    else:
        failed.append(("散文被误判", text))

# edge cases must not throw
for weird in ["", None, "a" * 600, "∫" * 3, "。"]:
    try:
        looks_like_formula(weird)
        passed += 1
    except Exception as exc:  # pragma: no cover
        failed.append(("异常", str(exc)))

print("%d passed, %d failed" % (passed, len(failed)))
for kind, text in failed:
    print("  FAIL %s：%r" % (kind, text))
sys.exit(0 if not failed else 1)
