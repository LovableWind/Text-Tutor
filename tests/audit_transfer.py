# -*- coding: utf-8 -*-
"""Same grounding audit, different handout (线性代数) — checks the mechanism is
not tuned to the calculus sample.

    $env:DSK = "sk-..."
    python tests/audit_transfer.py
"""

from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, HERE)

import handout as H  # noqa: E402
import guard  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
from audit_grounding import audit, build_index  # noqa: E402

CASES = [
    {
        "name": "L1 定义1.1 矩阵乘法（范围内）",
        "page": 1,
        "text": "定义 1.1 设 A=(a_ij) 是 m×n 矩阵，B=(b_ij) 是 n×p 矩阵，则 AB 是 m×p 矩阵，其第 i 行第 j 列元素为 sum a_ik b_kj。",
        "later": ["行列式", "det", "可逆", "逆矩阵", "特征值"],
        "outside": ["迹", "奇异值"],
    },
    {
        "name": "L1 越界提问：怎么判断可逆",
        "page": 1,
        "text": "怎么判断一个矩阵 A 是不是可逆的？",
        "later": ["行列式", "det", "逆矩阵"],
        "outside": ["奇异值分解", "SVD"],
    },
    {
        "name": "L2 定理1.1（行列式乘性）",
        "page": 2,
        "text": "定理 1.1 行列式的性质：det(AB) = det A · det B。",
        "later": ["特征值", "线性无关", "对角化"],
        "outside": ["迹"],
    },
    {
        "name": "L3 例2.1（线性相关判断）",
        "page": 3,
        "text": "例 2.1 判断 (1,0),(0,1),(1,1) 是否线性相关。",
        "later": ["特征值", "对角化", "可逆"],
        "outside": ["奇异值"],
    },
    {
        "name": "L4 习题2.1 提示 L1",
        "page": 4,
        "text": "习题 2.1 求 A=[[2,1],[1,2]] 的特征值与特征向量。",
        "later": [],
        "outside": ["若尔当", "相似"],
        "mode": "hint",
        "level": 1,
        "need_citation": True,
    },
    {
        "name": "L4 习题2.1 完整解答",
        "page": 4,
        "text": "习题 2.1 求 A=[[2,1],[1,2]] 的特征值与特征向量。",
        "later": [],
        "outside": ["若尔当", "相似"],
        "mode": "solution",
        "need_citation": True,
    },
]


def main():
    key = os.environ.get("DSK", "")
    if not key:
        print("missing $env:DSK")
        return 2
    rec = H.build_handout(os.path.join(ROOT, "samples", "线性代数示例.pdf"), "线性代数示例")
    stmts, sections = build_index(rec)
    settings = {
        "protocol": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-flash",
        "api_key": key,
        "max_tokens": 1400,
        "temperature": 0.4,
        "thinking": os.environ.get("DSH_THINKING") or "disabled",
    }
    bad = 0
    for case in CASES:
        system, messages = prompts.build_messages(
            rec, case["page"], case["text"],
            mode=case.get("mode", "explain"),
            hint_level=case.get("level", 1),
            exercise=case.get("exercise", False),
        )
        t0 = time.time()
        answer = llm.stream_chat(settings, system, messages).text.strip()
        problems, flagged = audit(answer, case["page"], stmts, sections, case)
        repaired = False
        if problems and os.environ.get("NO_REPAIR") != "1":
            fixed = guard.repair(settings, system, messages, answer, problems, case["page"], rec)
            if fixed:
                repaired = True
                answer = fixed
                problems, flagged = audit(answer, case["page"], stmts, sections, case)
        print("\n=== %s [%s] %.1fs%s" % (
            case["name"], "PASS" if not problems else "FAIL", time.time() - t0,
            " · 自查修正过" if repaired else ""))
        for line in flagged[:4]:
            print("    " + line.strip()[:110])
        for p in problems:
            print("  ! " + p)
            bad += 1
        if os.environ.get("VERBOSE"):
            print(answer)
    print("\n%d/%d cases clean" % (len(CASES) - bad, len(CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
