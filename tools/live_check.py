# -*- coding: utf-8 -*-
"""Manual quality check against the real endpoint.  Reads the key from the
environment (never from disk) so nothing secret is written by this script.

    $env:DSK = "sk-..."
    python tools/live_check.py "选中的文字" 2
"""

from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

import handout as handout_mod  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402


def main():
    selection = sys.argv[1] if len(sys.argv) > 1 else "例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。"
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    mode = sys.argv[3] if len(sys.argv) > 3 else "explain"

    record = handout_mod.build_handout(os.path.join(ROOT, "samples", "示例讲义.pdf"), "示例讲义")
    system, messages = prompts.build_messages(record, page, selection, mode=mode, hint_level=1)
    if os.environ.get("SHOW_PROMPT"):
        print(system)
        print("-" * 60)

    settings = {
        "protocol": "anthropic",
        "base_url": os.environ.get("DSH_BASE") or "https://api.deepseek.com/anthropic",
        "model": os.environ.get("DSH_MODEL") or "deepseek-flash",
        "api_key": os.environ.get("DSK") or "",
        "max_tokens": 1600,
        "temperature": 0.6,
    }
    if not settings["api_key"]:
        print("missing $env:DSK")
        return 2

    t0 = time.time()
    first = [None]

    def on_text(piece):
        if first[0] is None:
            first[0] = time.time() - t0
        sys.stdout.write(piece)
        sys.stdout.flush()

    res = llm.stream_chat(settings, system, messages, on_text)
    print("\n" + "-" * 60)
    print("elapsed %.1fs · first token %.1fs · in %d out %d cache %d" % (
        time.time() - t0, first[0] or -1, res.usage.input_tokens, res.usage.output_tokens, res.usage.cache_read))
    return 0


if __name__ == "__main__":
    sys.exit(main())
