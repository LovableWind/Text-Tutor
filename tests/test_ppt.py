# -*- coding: utf-8 -*-
"""旧版 .ppt 解析测试：CFB 读取、记录遍历、按幻灯片切分。"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ppttext  # noqa: E402
import make_sample_ppt  # noqa: E402

passed, failed = 0, []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   " + name)
    else:
        failed.append(name)
        print("  FAIL " + name + " " + str(detail))


SLIDES = [
    "第一章 极限 1.1 数列的极限 定义 1.1 若对任意 ε>0，存在 N",
    "1.2 收敛数列的性质 定理 1.1 收敛数列的极限唯一",
    "习题 1.1 用定义证明 lim (n+1)/n = 1",
]


def main():
    data = make_sample_ppt.build(SLIDES)
    check("built a compound file", data[:8] == ppttext.CFB_MAGIC, data[:8])

    pages = ppttext.extract_pages(data)
    check("slide count", len(pages) == 3, len(pages))
    check("slide numbers", [p["n"] for p in pages] == [1, 2, 3], [p["n"] for p in pages])
    check("first slide text", SLIDES[0] in pages[0]["text"], pages[0]["text"][:60])
    check("last slide text", SLIDES[2] in pages[2]["text"], pages[2]["text"][:60])
    check("no control chars", all("\r" not in p["text"] and "\x0b" not in p["text"] for p in pages))

    # 结构边界
    try:
        ppttext.extract_pages(b"not a ppt at all" * 100)
        check("garbage rejected", False)
    except ppttext.PptError:
        check("garbage rejected", True)

    check("magic sniff", ppttext.looks_like_ppt(data) and not ppttext.looks_like_ppt(b"\x00" * 600))

    # 章节空幻灯片也不该崩
    empty = make_sample_ppt.build([""])
    pages2 = ppttext.extract_pages(empty)
    check("empty slide still parses", len(pages2) == 1, len(pages2))

    # 仓库里的样例能读
    sample = os.path.join(ROOT, "samples", "课件示例", "第3讲 导数的应用.ppt")
    if os.path.exists(sample):
        pages3 = ppttext.extract_pages(open(sample, "rb").read())
        check("sample file parses", len(pages3) == 4, len(pages3))
        check("sample has 习题", any("习题" in p["text"] for p in pages3))

    # 和课件库打通：kind / 页数 / 讲次
    import corpus
    sample_path = "samples/课件示例/第3讲 导数的应用.ppt"
    if os.path.exists(sample_path):
        doc = corpus.build_doc("第3讲 导数的应用.ppt", open(sample_path, "rb").read())
        check("corpus kind", doc["kind"] == "ppt", doc["kind"])
        check("corpus pages", len(doc["pages"]) == 4, len(doc["pages"]))
        check("corpus ordinal", doc["ordinal"] == 3, doc["ordinal"])
        check("corpus domain", doc["domain"] == "math", doc["domain"])

    print("\n%d passed, %d failed" % (passed, len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
