# -*- coding: utf-8 -*-
"""上传前的自检：这次会传哪些文件？有没有不该出现的东西？

    python tools/check_upload.py

只读，不改任何文件。发现可疑项时以非零退出码结束。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FOLDERS = ["app", "web", "tools", "tests", "samples", ".github"]
ROOT_FILES = ["README.md", "使用说明.md", "LICENSE", "CHANGELOG.md", ".gitignore", ".gitattributes"]

# 这些出现在上传清单里就是错的
BAD_SUFFIX = (".pyc", ".pyo", ".pyd", ".log", ".tmp", ".swp")
BAD_DIRS = ("__pycache__", "dist", "data", ".git", ".e2e-tmp", ".e2e-corpus",
            ".live-tmp", ".test-capture", ".repro", ".tmp-local", ".boot-test")


def walk(base: str):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs]
        for name in files:
            yield os.path.join(root, name)


def main() -> int:
    files = []
    for folder in FOLDERS:
        path = os.path.join(ROOT, folder)
        if os.path.isdir(path):
            files.extend(walk(path))
    for name in ROOT_FILES:
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            files.append(path)

    rel = sorted(os.path.relpath(f, ROOT) for f in files)
    bad = []
    for r in rel:
        norm = r.replace("\\", "/")
        parts = norm.split("/")
        if any(p in BAD_DIRS for p in parts):
            bad.append((r, "不该上传的目录"))
        elif norm.endswith(BAD_SUFFIX):
            bad.append((r, "缓存/临时文件"))
        elif len(parts) == 1 and norm.startswith(".") and norm not in (".gitignore", ".gitattributes"):
            bad.append((r, "可疑的隐藏文件"))

    print("将上传 %d 个文件" % len(rel))
    for folder in FOLDERS + [""]:
        group = [r for r in rel if (r.startswith(folder + os.sep) if folder else os.sep not in r)]
        if group:
            label = folder or "根目录"
            print("  %-10s %d" % (label, len(group)))

    if bad:
        print("\n发现 %d 个不该上传的文件：" % len(bad))
        for name, why in bad[:40]:
            print("  ! %-52s %s" % (name, why))
        if len(bad) > 40:
            print("  … 还有 %d 个" % (len(bad) - 40))
        print("\n先运行：python tools\\clean.py")
        return 1

    print("\n没有发现缓存或临时文件，可以拖去上传。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
