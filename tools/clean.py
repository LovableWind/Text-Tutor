# -*- coding: utf-8 -*-
"""清掉不该进仓库的东西：字节码缓存、测试临时目录、临时 PDF。

    python tools/clean.py            # 只清源码树
    python tools/clean.py --dist     # 顺便只保留 dist 里最新的那个 zip
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JUNK_DIRS = [
    "__pycache__", ".e2e-tmp", ".e2e-corpus", ".live-tmp", ".test-capture",
    ".repro", ".tmp-local", ".boot-test", ".dist-tmp",
]
JUNK_FILES = [".corpus-tmp.pdf", ".tmp"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", action="store_true", help="只保留 dist 里最大的（最新的）zip")
    args = ap.parse_args()

    removed = []

    for root, dirs, files in os.walk(ROOT):
        if os.path.basename(root) == "dist":
            dirs[:] = []
            continue
        for d in list(dirs):
            if d in JUNK_DIRS:
                path = os.path.join(root, d)
                shutil.rmtree(path, ignore_errors=True)
                removed.append(os.path.relpath(path, ROOT))
                dirs.remove(d)
        for f in files:
            if f in JUNK_FILES:
                path = os.path.join(root, f)
                try:
                    os.remove(path)
                    removed.append(os.path.relpath(path, ROOT))
                except OSError:
                    pass

    if args.dist:
        dist = os.path.join(ROOT, "dist")
        if os.path.isdir(dist):
            zips = [
                os.path.join(dist, n) for n in os.listdir(dist)
                if n.lower().endswith(".zip") and re.search(r"v?\d+\.\d+", n)
            ]
            if len(zips) > 1:
                zips.sort(key=lambda p: os.path.getmtime(p))
                for old in zips[:-1]:
                    try:
                        os.remove(old)
                        removed.append(os.path.relpath(old, ROOT))
                    except OSError:
                        pass

    if removed:
        print("清掉 %d 项：" % len(removed))
        for item in removed:
            print("  - " + item)
    else:
        print("没有需要清理的东西。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
