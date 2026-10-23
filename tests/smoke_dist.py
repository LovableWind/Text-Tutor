# -*- coding: utf-8 -*-
"""Smoke-test the packaged portable build (dist/旁批) with the fake model."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist", "旁批")
DATA = os.path.join(ROOT, ".dist-tmp")

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print("  ok   " + name)
    else:
        bad.append(name)
        print("  FAIL " + name + " " + str(detail))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    INT = os.path.join(DIST, "_internal")
    py = os.path.join(INT, "runtime", "python.exe")
    check("runtime exists", os.path.exists(py), py)
    check("launcher exists", os.path.exists(os.path.join(DIST, "启动旁批.bat")))
    check("docs shipped", os.path.exists(os.path.join(DIST, "使用说明.md")))
    check("sample shipped", os.path.exists(os.path.join(INT, "samples", "示例讲义.pdf")))
    check("internal only", not os.path.exists(os.path.join(DIST, "app")))
    check("icon shipped", os.path.exists(os.path.join(INT, "web", "favicon.ico")))

    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    mock_port = free_port()
    mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_llm.py"), str(mock_port),
                             os.path.join(DATA, "sys.txt")])
    srv = subprocess.Popen([py, os.path.join(INT, "app", "server.py"), "--no-window", "--no-hotkey",
                            "--keep-alive", "--data-dir", DATA],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        info_path = os.path.join(DATA, "server.json")
        for _ in range(100):
            if os.path.exists(info_path):
                break
            time.sleep(0.2)
        if not os.path.exists(info_path):
            out = srv.stdout.read() if srv.poll() is not None else ""
            print("server did not start:\n", out)
            return 1
        info = json.load(open(info_path, encoding="utf-8"))
        base = "http://127.0.0.1:%d" % info["port"]
        H = {"X-Pangpi-Token": info["token"], "Content-Type": "application/json"}

        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        check("index served", "<title>旁批" in html)
        check("math.js served", b"MathRender" in urllib.request.urlopen(base + "/static/math.js").read())
        check("md.js served", b"MDRender" in urllib.request.urlopen(base + "/static/md.js").read())

        req = urllib.request.Request(base + "/api/state", headers=H)
        state = json.loads(urllib.request.urlopen(req).read())
        check("state ok", state["settings"]["has_key"] is False)

        payload = {"api_key": "sk-test", "base_url": "http://127.0.0.1:%d/anthropic" % mock_port,
                   "protocol": "anthropic", "model": "mock"}
        urllib.request.urlopen(urllib.request.Request(
            base + "/api/settings", data=json.dumps(payload).encode(), headers=H, method="POST"))

        pdf = open(os.path.join(INT, "samples", "示例讲义.pdf"), "rb").read()
        hh = dict(H)
        hh["X-Filename"] = "sample.pdf"
        urllib.request.urlopen(urllib.request.Request(base + "/api/handout", data=pdf, headers=hh, method="POST"))
        st = {}
        for _ in range(100):
            st = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/handout/status", headers=H)).read())
            if st["state"] in ("ready", "error"):
                break
            time.sleep(0.2)
        check("handout indexed", st.get("state") == "ready", st)

        req = urllib.request.Request(base + "/api/explain",
                                     data=json.dumps({"text": "定理 1.4 单调有界数列必有极限", "mode": "explain"}).encode(),
                                     headers=H, method="POST")
        deltas, done = 0, None
        with urllib.request.urlopen(req, timeout=60) as resp:
            buf = ""
            while True:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(512)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
                while "\n\n" in buf:
                    raw, buf = buf.split("\n\n", 1)
                    ev, data = "message", ""
                    for line in raw.split("\n"):
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                        elif line.startswith("data:"):
                            data += line[5:].strip()
                    if not data:
                        continue
                    obj = json.loads(data)
                    if ev == "delta":
                        deltas += 1
                    elif ev == "done":
                        done = obj
        check("stream produced text", deltas > 3, deltas)
        check("stream finished", done is not None)
        check("answer stored", done and "定位" in done["card"]["answer"])
        print("\n%d passed, %d failed" % (ok, len(bad)))
        return 0 if not bad else 1
    finally:
        srv.terminate()
        mock.terminate()
        time.sleep(0.3)
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
