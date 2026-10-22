# -*- coding: utf-8 -*-
"""End-to-end test for the multi-deck corpus (PPTX) with the fake model."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
DATA = os.path.join(ROOT, ".e2e-corpus")
DECKS = os.path.join(ROOT, "samples", "课件示例")

passed, failed = 0, []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   " + name)
    else:
        failed.append(name)
        print("  FAIL " + name + " " + str(detail))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    mock_port = free_port()
    dump = os.path.join(DATA, "system.txt")
    mock = subprocess.Popen([PY, os.path.join(HERE, "mock_llm.py"), str(mock_port), dump])
    srv = subprocess.Popen(
        [PY, os.path.join(ROOT, "app", "server.py"), "--no-window", "--no-hotkey",
         "--keep-alive", "--data-dir", os.path.join(DATA, "data")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        info_path = os.path.join(DATA, "data", "server.json")
        for _ in range(80):
            if os.path.exists(info_path):
                break
            time.sleep(0.2)
        info = json.load(open(info_path, encoding="utf-8"))
        base = "http://127.0.0.1:%d" % info["port"]
        H = {"X-Pangpi-Token": info["token"], "Content-Type": "application/json"}

        def post(path, payload, headers=None):
            hh = dict(H)
            hh.update(headers or {})
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            req = urllib.request.Request(base + path, data=body, headers=hh, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=60).read())

        def get(path):
            req = urllib.request.Request(base + path, headers=H)
            return json.loads(urllib.request.urlopen(req, timeout=60).read())

        # model points at the fake endpoint
        post("/api/settings", {"api_key": "sk-test", "protocol": "anthropic",
                               "base_url": "http://127.0.0.1:%d/anthropic" % mock_port,
                               "model": "mock"})

        for name in ["第10讲 微分方程初步.pptx", "第1讲 极限与连续.pptx", "第2讲 导数与微分.pptx"]:
            data = open(os.path.join(DECKS, name), "rb").read()
            res = post("/api/corpus/add", data,
                       {"X-Filename": urllib.parse.quote(name), "Content-Type": "application/octet-stream"})
            check("add %s" % name, res.get("ok") is True, res.get("error"))

        corpus = get("/api/corpus")
        names = [d["name"] for d in corpus["docs"]]
        check("natural order 1<2<10", names == ["第1讲 极限与连续.pptx", "第2讲 导数与微分.pptx", "第10讲 微分方程初步.pptx"], names)
        check("page counts", [d["pages"] for d in corpus["docs"]] == [6, 5, 3], corpus["docs"])
        check("outline found", all(d["outline"] for d in corpus["docs"]))

        # position: lecture 2, page 3
        res = post("/api/corpus/position", {"doc": 1, "page": 3})
        check("position set", res["corpus"]["current"]["doc"] == 1 and res["corpus"]["current"]["page"] == 3, res)
        check("section resolved", res["corpus"]["current"]["section"].startswith("2.1"), res["corpus"]["current"])

        # explain something from lecture 1 while sitting in lecture 2 -> auto locate
        req = urllib.request.Request(
            base + "/api/explain",
            data=json.dumps({"text": "对任意 ε>0，存在 N，当 n>N 时 |a_n - A| < ε", "mode": "explain"}).encode(),
            headers=H, method="POST")
        done = None
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
                    if ev == "done":
                        done = obj
        check("explain done", done is not None)
        card = (done or {}).get("card", {})
        check("located in lecture 1", card.get("doc") == 0, card.get("doc"))
        check("card names the deck", "第1讲" in (card.get("doc_name") or ""), card.get("doc_name"))

        system = open(dump, encoding="utf-8").read()
        check("prompt has course structure", "课程结构" in system)
        check("prompt has covered label", "第 1–" in system or "还没有讲过" in system)
        check("prompt lists all three decks", system.count(".pptx") >= 3)

        # reorder: put lecture 10 first, check that covered range follows the new order
        order = [d["id"] for d in corpus["docs"]][::-1]
        res = post("/api/corpus/reorder", {"order": order})
        check("reorder applied", [d["name"] for d in res["corpus"]["docs"]][0].startswith("第10讲"))

        # delete
        victim = res["corpus"]["docs"][0]["id"]
        res = post("/api/corpus/delete", {"id": victim})
        check("delete applied", len(res["corpus"]["docs"]) == 2)

        print("\n%d passed, %d failed" % (passed, len(failed)))
        if failed:
            print("failed:", ", ".join(failed))
        return 0 if not failed else 1
    finally:
        srv.terminate()
        mock.terminate()
        time.sleep(0.3)
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
