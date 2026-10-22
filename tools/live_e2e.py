# -*- coding: utf-8 -*-
"""Drive the real server against the real model, printing the streamed answer.

    $env:DSK = "sk-..."
    python tools/live_e2e.py "选中的文字" 2
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, ".live-tmp")


def main():
    selection = sys.argv[1] if len(sys.argv) > 1 else "例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。"
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    key = os.environ.get("DSK", "")
    if not key:
        print("missing $env:DSK")
        return 2

    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "app", "server.py"), "--no-window", "--no-hotkey",
         "--keep-alive", "--data-dir", DATA],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )
    try:
        info_path = os.path.join(DATA, "server.json")
        for _ in range(80):
            if os.path.exists(info_path):
                break
            time.sleep(0.2)
        info = json.load(open(info_path, encoding="utf-8"))
        base = "http://127.0.0.1:%d" % info["port"]
        H = {"X-Pangpi-Token": info["token"], "Content-Type": "application/json"}

        def post(path, payload):
            req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers=H, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=30).read())

        post("/api/settings", {
            "api_key": key, "protocol": "anthropic",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": "deepseek-flash", "thinking": "disabled", "max_tokens": 1600,
        })
        pdf = open(os.path.join(ROOT, "samples", "示例讲义.pdf"), "rb").read()
        hh = dict(H)
        hh["X-Filename"] = "%E7%A4%BA%E4%BE%8B%E8%AE%B2%E4%B9%89.pdf"
        urllib.request.urlopen(urllib.request.Request(base + "/api/handout", data=pdf, headers=hh, method="POST"), timeout=30)
        for _ in range(100):
            st = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/handout/status", headers=H)).read())
            if st["state"] in ("ready", "error"):
                break
            time.sleep(0.2)
        print("handout:", st.get("state"), st.get("message", ""))

        t0 = time.time()
        req = urllib.request.Request(
            base + "/api/explain",
            data=json.dumps({"text": selection, "mode": "explain", "page": page}).encode(),
            headers=H, method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            buf = ""
            while True:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(512)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
                while "\n\n" in buf:
                    raw, buf = buf.split("\n\n", 1)
                    event, data = "message", ""
                    for line in raw.split("\n"):
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            data += line[5:].strip()
                    if not data:
                        continue
                    payload = json.loads(data)
                    if event == "delta":
                        sys.stdout.write(payload["text"])
                        sys.stdout.flush()
                    elif event in ("notice", "note"):
                        print("\n[" + event + "]", payload.get("text"))
                    elif event == "replace":
                        print("\n[replace]", payload.get("issues"))
                    elif event == "done":
                        print("\n\n[done in %.1fs] usage=%s" % (time.time() - t0, payload["card"].get("usage")))
                    elif event == "error":
                        print("\n[error]", payload.get("message"))
        state = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/state", headers=H)).read())
        print("cards:", len(state["cards"]), "page:", state["page"], "section:", (state.get("section") or {}).get("title"))
        return 0
    finally:
        proc.terminate()
        time.sleep(0.3)


if __name__ == "__main__":
    sys.exit(main())
