# -*- coding: utf-8 -*-
"""End-to-end test: real server + fake model endpoint.  Run: python tests/e2e.py"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

passed = 0
failed = []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed.append(name)
        print("  FAIL %s %s" % (name, detail))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(url, method="GET", body=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def sse(url, payload, headers, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        buf = ""
        while True:
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
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
                if data:
                    events.append((event, json.loads(data)))
    return events


def main():
    tmp = os.path.join(ROOT, ".e2e-tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    print("workdir:", tmp)
    mock_port = free_port()
    prompt_dump = os.path.join(tmp, "system.txt")
    mock = subprocess.Popen([PY, os.path.join(HERE, "mock_llm.py"), str(mock_port), prompt_dump])
    server = subprocess.Popen(
        [PY, os.path.join(ROOT, "app", "server.py"), "--no-window", "--no-hotkey",
         "--keep-alive", "--data-dir", os.path.join(tmp, "data")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )
    try:
        info_path = os.path.join(tmp, "data", "server.json")
        for _ in range(60):
            if os.path.exists(info_path):
                break
            time.sleep(0.2)
        info = json.load(open(info_path, encoding="utf-8"))
        base = "http://127.0.0.1:%d" % info["port"]
        token = info["token"]
        H = {"X-Pangpi-Token": token, "Content-Type": "application/json"}
        print("server:", base)

        # 1. static shell
        html = request(base + "/").read().decode("utf-8")
        check("index served", "<title>旁批" in html)
        css = request(base + "/static/styles.css").read()
        check("css served", b"--accent" in css)
        js = request(base + "/static/app.js").read()
        check("js served", b"streamPost" in js)

        # 2. auth
        try:
            request(base + "/api/state")
            check("auth required", False)
        except urllib.error.HTTPError as exc:
            check("auth required", exc.code == 401)

        state = json.loads(request(base + "/api/state", headers=H).read())
        check("state shape", "settings" in state and "handout" in state)
        check("no key yet", state["settings"]["has_key"] is False)

        # 3. settings
        payload = {
            "protocol": "anthropic",
            "base_url": "http://127.0.0.1:%d/anthropic" % mock_port,
            "model": "mock-model",
            "api_key": "sk-test-1234567890",
        }
        res = json.loads(request(base + "/api/settings", "POST", json.dumps(payload).encode(), H).read())
        check("settings saved", res["settings"]["has_key"] and res["settings"]["key_hint"].startswith("sk-t"))

        # 4. handout upload
        pdf = open(os.path.join(ROOT, "samples", "示例讲义.pdf"), "rb").read()
        hh = dict(H)
        hh["X-Filename"] = "%E7%A4%BA%E4%BE%8B%E8%AE%B2%E4%B9%89.pdf"
        res = json.loads(request(base + "/api/handout", "POST", pdf, hh).read())
        check("upload accepted", res.get("ok") is True)
        for _ in range(80):
            st = json.loads(request(base + "/api/handout/status", headers=H).read())
            if st["state"] in ("ready", "error"):
                break
            time.sleep(0.2)
        check("handout parsed", st["state"] == "ready", st)
        state = json.loads(request(base + "/api/state", headers=H).read())
        check("handout meta", state["handout"]["page_count"] == 4)
        check("outline detected", len(state["handout"]["outline"]) >= 4, state["handout"]["outline"])

        # 5. page switch
        res = json.loads(request(base + "/api/page", "POST", b'{"page":2}', H).read())
        check("page switch", res["page"] == 2 and res["section"]["title"].startswith("1.3"))

        # 6. explain stream
        events = sse(base + "/api/explain", {
            "text": "设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。",
            "mode": "explain",
            "page": 2,
        }, H)
        kinds = [e[0] for e in events]
        check("stream meta", "meta" in kinds)
        check("stream deltas", kinds.count("delta") > 5)
        done = [e[1] for e in events if e[0] == "done"]
        check("stream done", bool(done))
        text = done[0]["card"]["answer"] if done else ""
        check("answer has math", "$" in text and "定位" in text)
        check("answer has later-cite", "⏭" in text)
        check("answer has supplement", "➕" in text)
        check("usage recorded", done and done[0]["card"]["usage"]["input"] == 1200)

        system = open(prompt_dump, encoding="utf-8").read()
        check("prompt has prior-range", "已讲范围" in system)
        check("prompt has toc", "目录" in system)
        check("prompt names handout", "示例讲义" in system)
        check("prompt restricts rules", "硬性规则" in system)

        # 6a. an exercise asks first and does not call the model
        ex_text = "Exercise 3.2  Show that the sequence is bounded."
        events = sse(base + "/api/explain", {"text": ex_text, "mode": "auto", "page": 2}, H)
        kinds = [e[0] for e in events]
        check("exercise asks before explaining", "ask" in kinds and "delta" not in kinds, kinds)
        ask_card = [e[1] for e in events if e[0] == "ask"][0]["card"]
        check("ask card has no answer", ask_card.get("answer") == "" and ask_card.get("status") == "ask")
        check("ask offers three modes", [e[1] for e in events if e[0] == "ask"][0]["modes"] == ["translate", "hint", "explain"])

        # explicit translate runs the model in translate mode
        events = sse(base + "/api/explain", {"text": ex_text, "mode": "translate", "page": 2}, H)
        tdone = [e[1] for e in events if e[0] == "done"]
        check("translate mode runs", bool(tdone) and tdone[0]["card"]["mode"] == "translate")
        tsystem = open(prompt_dump, encoding="utf-8").read()
        check("translate prompt forbids solving", "不要讲解" in tsystem or "不要解题" in tsystem)

        # a non-exercise selection in auto mode still explains directly
        events = sse(base + "/api/explain", {"text": "定理 1.4 单调有界数列必有极限。", "mode": "auto", "page": 2}, H)
        kinds = [e[0] for e in events]
        check("auto explains non-exercises", "done" in kinds and "ask" not in kinds, kinds)

        # 6b. a formula-shaped selection is flagged, and the prompt warns about
        # text-layer loss (superscripts / radicals disappear when copying).
        events = sse(base + "/api/explain", {
            "text": "∫x2dx = F(b) - F(a)",
            "mode": "explain",
            "page": 2,
        }, H)
        fdone = [e[1] for e in events if e[0] == "done"]
        check("formula card flagged", bool(fdone) and fdone[0]["card"].get("formula") is True)
        fsystem = open(prompt_dump, encoding="utf-8").read()
        check("formula prompt warns about text layer", "文字层" in fsystem and "框选截图" in fsystem)

        # 7. hint mode
        events = sse(base + "/api/explain", {
            "text": "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
            "mode": "hint",
            "hint_level": 1,
            "page": 4,
        }, H)
        hint_done = [e[1] for e in events if e[0] == "done"]
        check("hint stream", bool(hint_done) and "提示" in hint_done[0]["card"]["answer"])
        check("hint level stored", hint_done and hint_done[0]["card"]["hint_level"] == 1)

        # 8. follow-up
        card_id = done[0]["card"]["id"]
        events = sse(base + "/api/chat", {"card_id": card_id, "question": "为什么上界是 2？"}, H)
        chat_done = [e[1] for e in events if e[0] == "done"]
        check("chat stream", bool(chat_done) and chat_done[0]["message"]["role"] == "assistant")

        state = json.loads(request(base + "/api/state", headers=H).read())
        check("cards persisted", len(state["cards"]) >= 2)
        check("thread stored", any(c.get("thread") for c in state["cards"]))

        # 9. locate
        res = json.loads(request(base + "/api/locate", "POST",
                                 json.dumps({"text": "可导必连续，连续不一定可导"}).encode(), H).read())
        check("locate page", res.get("page") == 3, res)

        # 9b. the guide page and the "new set of handouts" reset
        guide = request(base + "/guide").read().decode("utf-8")
        check("guide page served", "使用说明" in guide or "旁批" in guide, len(guide))
        check("guide page is html", guide.lstrip().startswith("<!doctype html"))

        state_before = json.loads(request(base + "/api/state", headers=H).read())
        res = json.loads(request(base + "/api/session/reset", "POST", b"{}", H).read())
        check("reset clears handout", res["handout"]["ready"] is False)
        check("reset clears corpus", res["corpus"]["ready"] is False, res["corpus"])
        state_after = json.loads(request(base + "/api/state", headers=H).read())
        check("reset keeps settings", state_after["settings"]["has_key"] == state_before["settings"]["has_key"])

        # 9c. shutdown handshake (the page sends this on window close)
        res = json.loads(request(base + "/api/goodbye", "POST", b"{}", H).read())
        check("goodbye accepted", res.get("ok") is True)
        res = json.loads(request(base + "/api/ping", "POST", b"{}", H).read())
        check("ping after goodbye cancels exit", res.get("ok") is True)

        # 10. image upload path
        import base64
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        events = sse(base + "/api/explain", {"text": "", "mode": "explain", "image": base64.b64encode(png).decode()}, H)
        check("image explain", any(e[0] == "done" for e in events))

        # 11. error path: bad key
        json.loads(request(base + "/api/settings", "POST", b'{"api_key":""}', H).read())
        events = sse(base + "/api/explain", {"text": "测试"}, H)
        errs = [e[1] for e in events if e[0] == "error"]
        check("no-key error", bool(errs) and "API Key" in errs[0]["message"])

        print("\n%d passed, %d failed" % (passed, len(failed)))
        if failed:
            print("failed:", ", ".join(failed))
            print(server.stdout.read() if server.poll() is not None else "")
        return 0 if not failed else 1
    finally:
        server.terminate()
        mock.terminate()
        time.sleep(0.3)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
