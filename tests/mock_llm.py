# -*- coding: utf-8 -*-
"""A tiny fake model endpoint so the app can be tested without a real API key."""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = """**定位**：这段在用数列极限的 ε-N 定义，说明 (n+1)/n → 1。

**讲解**：
1. 把通项拆开：$(n+1)/n = 1 + 1/n$，所以 $|(n+1)/n - 1| = 1/n$。
2. 要让 $1/n < \\varepsilon$，只需 $n > 1/\\varepsilon$。
3. 取 $N = [1/\\varepsilon] + 1$，则当 $n > N$ 时 $1/n < \\varepsilon$ 成立。

$$\\lim_{n \\to \\infty} \\frac{n+1}{n} = 1$$

**依据**：第 1 页的定义 1.1（数列极限的 ε-N 定义）。

⏭ 引申 · 第2节《收敛数列的性质》（第 1 页）：那里用这个定义推出极限唯一性。

➕ 补充：这里用到阿基米德性质——对任意正数 $\\varepsilon$，总存在正整数 $n > 1/\\varepsilon$，它保证 N 取得到。

**易错点**：N 只要求存在，不要求最小；换成 $N = [1/\\varepsilon]$ 在 $1/\\varepsilon$ 为整数时会差一点。
"""

HINT = """**提示（第1层）**：先别急着算极限。看一眼这个数列是单调递增还是单调递减，再用上界去卡住它。

**卡点**：多数人直接设极限为 $A$ 代进去，忘了先证明极限存在。
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw.decode("utf-8") or "{}")
        text = json.dumps(body.get("system", ""), ensure_ascii=False)
        with open(sys.argv[2], "w", encoding="utf-8") as fh:
            fh.write(text)
        reply = HINT if "第 1 层提示" in json.dumps(body, ensure_ascii=False) else REPLY
        if self.path.endswith("/messages"):
            self._anthropic(reply)
        else:
            self._openai(reply)

    def _start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _write(self, payload: bytes):
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except Exception:
            pass

    def _anthropic(self, text):
        self._start()
        self._write(b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":1200,"output_tokens":0}}}\n\n')
        self._write(b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}\n\n')
        for piece in ["先看定义，", "再看要证的式子。"]:
            chunk = {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": piece}}
            self._write(("event: content_block_delta\ndata: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode())
        self._write(b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n')
        self._write(b'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"text"}}\n\n')
        step = 14
        for i in range(0, len(text), step):
            piece = text[i : i + step]
            chunk = {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": piece}}
            self._write(("event: content_block_delta\ndata: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode())
            time.sleep(0.004)
        self._write(b'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}\n\n')
        self._write(b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":420}}\n\n')
        self._write(b'event: message_stop\ndata: {"type":"message_stop"}\n\n')

    def _openai(self, text):
        self._start()
        for i in range(0, len(text), 20):
            piece = text[i : i + 20]
            chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
            self._write(("data: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode())
        self._write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":900,"completion_tokens":300}}\n\n')
        self._write(b"data: [DONE]\n\n")


def main():
    port = int(sys.argv[1])
    dump = sys.argv[2]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    print("mock llm on %d" % port, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
