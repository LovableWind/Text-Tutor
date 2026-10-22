# -*- coding: utf-8 -*-
"""Capture de-duplication: one snip must not produce two cards."""

from __future__ import annotations

import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

import server as srv  # noqa: E402

DATA = os.path.join(ROOT, ".test-capture")

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
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    app = srv.App(DATA)
    events = []
    q = app.bus.subscribe()

    def drain():
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    png = b"\x89PNG\r\n\x1a\n" + b"x" * 200

    app.handle_capture({"text": "", "image": png}, "clipboard")
    check("first snip published", len(drain()) == 1)

    app.handle_capture({"text": "", "image": png}, "clipboard")
    check("same snip within 2.5s dropped", len(drain()) == 0)

    time.sleep(0.05)
    app.handle_capture({"text": "", "image": png + b"y"}, "clipboard")
    check("different image still published", len(drain()) == 1)

    app.handle_capture({"text": "定理 1.4 单调有界"}, "clipboard")
    check("text capture published", len(drain()) == 1)
    app.handle_capture({"text": "定理 1.4 单调有界"}, "clipboard")
    check("same text dropped", len(drain()) == 0)

    app.handle_capture({"text": "习题 2.1 求极限"}, "clipboard")
    check("different text published", len(drain()) == 1)

    print("\n%d passed, %d failed" % (passed, len(failed)))
    shutil.rmtree(DATA, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
