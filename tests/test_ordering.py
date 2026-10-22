# -*- coding: utf-8 -*-
"""Unit tests for lecture-number detection and deck ordering (app/corpus.py)."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))

from corpus import natural_key, ordinal_of  # noqa: E402

CASES = [
    # English spellings, including the common typo
    ("LECTURE_01.pptx", 1),
    ("LECTURE_07.pptx", 7),
    ("LECTER_07.pptx", 7),
    ("lecture 12.pdf", 12),
    ("Lecture3.pptx", 3),
    ("lect2_final.pptx", 2),
    ("Lec-04 傅里叶.pptx", 4),
    # 中文讲次
    ("第一讲 极限.pptx", 1),
    ("第二讲 导数.pptx", 2),
    ("第十讲 微分方程.pptx", 10),
    ("第 3 讲 积分.pdf", 3),
    # Chapter / Ch / Unit / Week
    ("Chapter 1.pptx", 1),
    ("chapter_12.pdf", 12),
    ("Ch.3.pptx", 3),
    ("ch5 向量.pdf", 5),
    ("Unit 4 矩阵.pptx", 4),
    ("Week 5.pptx", 5),
    # 裸序号
    ("一 绪论.pptx", 1),
    ("二、极限.pptx", 2),
    ("01. 概述.pdf", 1),
    ("3讲 积分.pptx", 3),
    # 没有序号
    ("syllabus.pdf", None),
    ("2024讲义.pdf", None),
    ("notes_final.pptx", None),
]

passed, failed = 0, []
for name, want in CASES:
    got = ordinal_of(name)
    if got == want:
        passed += 1
    else:
        failed.append("%r -> %r (want %r)" % (name, got, want))

ORDER_CASES = [
    (
        ["LECTURE_10.pptx", "LECTURE_02.pptx", "LECTURE_01.pptx"],
        ["LECTURE_01.pptx", "LECTURE_02.pptx", "LECTURE_10.pptx"],
    ),
    (
        ["第十讲.pptx", "第二讲.pptx", "第一讲.pptx"],
        ["第一讲.pptx", "第二讲.pptx", "第十讲.pptx"],
    ),
    (
        ["Chapter 3.pptx", "Chapter 1.pptx", "Chapter 2.pptx"],
        ["Chapter 1.pptx", "Chapter 2.pptx", "Chapter 3.pptx"],
    ),
    (
        ["二 极限.pptx", "一 绪论.pptx", "三 连续.pptx"],
        ["一 绪论.pptx", "二 极限.pptx", "三 连续.pptx"],
    ),
]

for names, want in ORDER_CASES:
    got = sorted(names, key=natural_key)
    if got == want:
        passed += 1
    else:
        failed.append("order %r -> %r" % (names, got))

# 混合写法 + 无序号文件排在最后
mixed = ["LECTURE_10.pptx", "第三讲.pptx", "syllabus.pdf", "Chapter 2.pptx", "一 绪论.pptx"]
got = sorted(mixed, key=natural_key)
want = ["一 绪论.pptx", "Chapter 2.pptx", "第三讲.pptx", "LECTURE_10.pptx", "syllabus.pdf"]
if got == want:
    passed += 1
else:
    failed.append("mixed -> %r" % (got,))

print("%d passed, %d failed" % (passed, len(failed)))
for item in failed:
    print("  FAIL", item)
sys.exit(0 if not failed else 1)
