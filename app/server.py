# -*- coding: utf-8 -*-
"""「旁批」local server: clipboard/hotkey capture, handout index, LLM streaming."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import queue
import random
import re
import socket
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import handout as handout_mod  # noqa: E402
import corpus as corpus_mod  # noqa: E402
import exercise  # noqa: E402
import formula  # noqa: E402
import guard  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
import win32  # noqa: E402

VERSION = "1.2.1"
APP_TITLE = "旁批"

DEFAULT_SETTINGS = {
    "protocol": "anthropic",
    "base_url": "https://api.deepseek.com/anthropic",
    "model": "deepseek-flash",
    "api_key": "",
    "max_tokens": 1600,
    "temperature": 0.4,
    "thinking": "disabled",
    "self_check": True,
    "hotkey": "Ctrl+Alt+D",
    "auto_listen": True,
    "theme": "dark",
    "font_size": 15,
    "width": 440,
}


# --------------------------------------------------------------------------
# paths / state
# --------------------------------------------------------------------------


def pick_data_dir(portable_root: str) -> str:
    candidate = os.path.join(portable_root, "data")
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".w")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("1")
        os.remove(probe)
        return candidate
    except Exception:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Pangpi")
        os.makedirs(path, exist_ok=True)
        return path


class Store:
    def __init__(self, root: str):
        self.root = root
        self.settings_path = os.path.join(root, "settings.json")
        self.handout_path = os.path.join(root, "handout.json")
        self.cards_path = os.path.join(root, "cards.json")
        self.corpus_path = os.path.join(root, "corpus.json")
        self.img_dir = os.path.join(root, "img")
        os.makedirs(self.img_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = self._load_settings()
        self.handout = handout_mod.load_handout(self.handout_path)
        self.corpus = corpus_mod.load(self.corpus_path) or corpus_mod.new_corpus()
        self.cards = self._load_cards()
        self.page = int(self.settings.get("page") or 1)
        self.doc = int(self.settings.get("doc") or 0)
        self.handout_status = {"state": "ready" if self.handout else "none", "progress": 0, "message": ""}

    # -- settings ---------------------------------------------------------
    def _load_settings(self) -> dict:
        data = dict(DEFAULT_SETTINGS)
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as fh:
                    data.update(json.load(fh) or {})
            except Exception:
                pass
        return data

    def save_settings(self):
        with self.lock:
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.settings_path)

    def public_settings(self) -> dict:
        s = dict(self.settings)
        key = s.pop("api_key", "") or ""
        s["has_key"] = bool(key)
        s["key_hint"] = ("%s……%s" % (key[:4], key[-4:])) if len(key) >= 12 else ("已保存" if key else "")
        return s

    # -- cards ------------------------------------------------------------
    def _load_cards(self) -> list:
        if os.path.exists(self.cards_path):
            try:
                with open(self.cards_path, "r", encoding="utf-8") as fh:
                    return json.load(fh) or []
            except Exception:
                return []
        return []

    def save_cards(self):
        with self.lock:
            tmp = self.cards_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.cards[-120:], fh, ensure_ascii=False)
            os.replace(tmp, self.cards_path)

    def save_corpus(self):
        with self.lock:
            corpus_mod.save(self.corpus, self.corpus_path)

    def add_card(self, card: dict) -> dict:
        with self.lock:
            self.cards.append(card)
            if len(self.cards) > 200:
                self.cards = self.cards[-200:]
        self.save_cards()
        return card

    def update_card(self, card_id: str, **fields) -> dict | None:
        with self.lock:
            for card in self.cards:
                if card.get("id") == card_id:
                    card.update(fields)
                    self.save_cards()
                    return card
        return None

    def get_card(self, card_id: str) -> dict | None:
        for card in self.cards:
            if card.get("id") == card_id:
                return card
        return None

    def delete_card(self, card_id: str):
        with self.lock:
            self.cards = [c for c in self.cards if c.get("id") != card_id]
        self.save_cards()

    # -- images -----------------------------------------------------------
    def save_image(self, data: bytes) -> str:
        img_id = uuid.uuid4().hex[:12]
        with open(os.path.join(self.img_dir, img_id + ".png"), "wb") as fh:
            fh.write(data)
        return img_id

    def load_image(self, img_id: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{6,32}", img_id or ""):
            return b""
        path = os.path.join(self.img_dir, img_id + ".png")
        if not os.path.exists(path):
            return b""
        with open(path, "rb") as fh:
            return fh.read()


# --------------------------------------------------------------------------
# event bus (SSE fan-out to the UI)
# --------------------------------------------------------------------------


class EventBus:
    def __init__(self):
        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self, event: dict):
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


# --------------------------------------------------------------------------
# app state
# --------------------------------------------------------------------------


def _looks_secret(text: str) -> bool:
    """Do not ship credentials to a model because someone pressed Ctrl+C."""
    t = text.strip()
    if re.fullmatch(r"(sk|pk|rk)-[A-Za-z0-9_\-]{16,}", t):
        return True
    if re.fullmatch(r"[A-Za-z0-9+/=_\-]{32,}", t):
        return True
    if re.search(r"(密码|口令|password|passwd|secret|token|api[_-]?key)\s*[:=]", t, re.I):
        return True
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", t):
        return True
    return False


class App:
    def __init__(self, data_dir: str):
        self.store = Store(data_dir)
        self.bus = EventBus()
        self.token = self._ensure_token()
        self.port = 0
        self.started = time.time()
        self.last_ping = time.time()
        self.exit_at = 0.0
        self._last_capture = (None, 0.0)
        self.window_opened = False
        self.suppress_until = 0.0
        self._parse_thread = None
        self.hotkey = win32.HotkeyListener()
        self.server: ThreadingHTTPServer | None = None

    def _ensure_token(self) -> str:
        path = os.path.join(self.store.root, "token")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    tok = fh.read().strip()
                if len(tok) >= 16:
                    return tok
            tok = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(tok)
            return tok
        except Exception:
            return hashlib.sha256(os.urandom(32)).hexdigest()[:32]

    # -- capture ----------------------------------------------------------
    def handle_capture(self, payload: dict, source: str):
        text = (payload.get("text") or "").strip()
        image = payload.get("image") or b""
        if not text and not image:
            return
        if text and _looks_secret(text):
            return

        # 一次截图常常让剪贴板序号跳两次（系统先写 DIB 再写 PNG），
        # 同一个内容 2.5 秒内只处理一次，避免弹出两张一样的卡片。
        key = ("img", hashlib.sha1(image).hexdigest()) if image else ("txt", text[:300])
        now = time.time()
        last_key, last_at = self._last_capture
        if key == last_key and now - last_at < 2.5:
            return
        self._last_capture = (key, now)
        event = {"type": "capture", "source": source, "ts": time.time() * 1000}
        if image:
            img_id = self.store.save_image(image)
            event["image_id"] = img_id
            event["text"] = text
        else:
            located = {"page": None, "score": 0.0}
            if self.store.handout:
                located = handout_mod.locate(self.store.handout, text)
            event["text"] = text
            event["page"] = located.get("page")
            event["score"] = located.get("score", 0.0)
        self.bus.publish(event)

    def start_watcher(self):
        def loop():
            last = win32.clipboard_sequence()
            while True:
                time.sleep(0.33)
                try:
                    if not self.store.settings.get("auto_listen", True):
                        last = win32.clipboard_sequence()
                        continue
                    seq = win32.clipboard_sequence()
                    if seq == last:
                        continue
                    last = seq
                    if time.time() < self.suppress_until:
                        continue
                    data = win32.read_clipboard()
                    if data["kind"] == "text":
                        text = data["text"]
                        if len(text) < 2 or len(text) > 4000:
                            continue
                        if text.startswith("http://127.0.0.1"):
                            continue
                        self.handle_capture({"text": text}, "clipboard")
                    elif data["kind"] == "image":
                        self.handle_capture({"text": "", "image": data["image"]}, "clipboard")
                except Exception:
                    time.sleep(1.0)

        threading.Thread(target=loop, name="clip-watch", daemon=True).start()

    def start_hotkey(self):
        spec = self.store.settings.get("hotkey") or "Ctrl+Alt+D"

        def on_hotkey():
            self.store.settings["_last_hotkey"] = time.time()
            grabbed = win32.grab_selection()
            if grabbed.get("kind") == "empty":
                time.sleep(0.12)
                grabbed = win32.read_clipboard()
            self.handle_capture(
                {"text": grabbed.get("text", ""), "image": grabbed.get("image", b"")}, "hotkey"
            )

        ok = self.hotkey.start(spec, on_hotkey)
        if not ok:
            print("[hotkey] 注册失败：%s（可能被其它软件占用）" % spec)

    # -- handout ----------------------------------------------------------
    def start_parse(self, pdf_bytes: bytes, filename: str) -> bool:
        if self._parse_thread and self._parse_thread.is_alive():
            return False

        def run():
            st = self.store.handout_status
            st.update({"state": "parsing", "progress": 5, "message": "正在解析 PDF…"})
            self.bus.publish({"type": "handout", "state": "parsing", "progress": 5})
            path = os.path.join(self.store.root, "handout.pdf")
            try:
                with open(path, "wb") as fh:
                    fh.write(pdf_bytes)
                st.update({"progress": 25, "message": "提取文字层…"})
                self.bus.publish({"type": "handout", "state": "parsing", "progress": 25})
                record = handout_mod.build_handout(path, filename)
                record["created"] = time.time()
                handout_mod.save_handout(record, self.store.handout_path)
                self.store.handout = record
                msg = {
                    "text": "已建立讲义索引：%d 页 / %d 字" % (record["page_count"], record["chars"]),
                    "scanned": "这份 PDF 没有可用的文字层（扫描或手写版）。仍然可以取词讲解，但页码需要你手动指定。",
                    "vector": "这份 PDF 的文字是矢量笔画、没有文字层，无法自动建索引。取词讲解仍然可用。",
                    "poor": "这份 PDF 的文字层质量较差，索引可能不准。",
                }.get(record["quality"] if record["quality"] != "text" else "text", "")
                st.update(
                    {
                        "state": "ready",
                        "progress": 100,
                        "message": msg,
                        "quality": record["quality"],
                        "pages": record["page_count"],
                        "outline": len(record["outline"]),
                    }
                )
                self.bus.publish({"type": "handout", "state": "ready", "progress": 100, "message": msg})
            except Exception as exc:
                traceback.print_exc()
                st.update({"state": "error", "message": "解析失败：%s" % exc})
                self.bus.publish({"type": "handout", "state": "error", "message": "解析失败：%s" % exc})

        self._parse_thread = threading.Thread(target=run, name="parse", daemon=True)
        self._parse_thread.start()
        return True

    def has_corpus(self) -> bool:
        return bool(self.store.corpus.get("docs"))

    def corpus_summary(self) -> dict:
        docs = self.store.corpus.get("docs") or []
        if not docs:
            return {"ready": False, "docs": [], "position": {"doc": 0, "page": 1}, "total_pages": 0}
        doc_idx = max(0, min(self.store.doc, len(docs) - 1))
        page = max(1, min(self.store.page, corpus_mod.page_count(docs[doc_idx]) or 1))
        summary = corpus_mod.summary(self.store.corpus, doc_idx, page)
        summary["ready"] = True
        summary["current"] = {
            "doc": doc_idx,
            "page": page,
            "name": docs[doc_idx]["name"],
            "pages": corpus_mod.page_count(docs[doc_idx]),
            "section": (corpus_mod.section_at(docs[doc_idx], page) or {}).get("title") or "",
        }
        return summary

    def handout_summary(self) -> dict:
        h = self.store.handout
        if not h:
            return {"ready": False, "status": self.store.handout_status}
        return {
            "ready": True,
            "name": h.get("name"),
            "page_count": h.get("page_count"),
            "chars": h.get("chars"),
            "quality": h.get("quality"),
            "outline": h.get("outline") or [],
            "status": self.store.handout_status,
        }

    # -- llm --------------------------------------------------------------
    def stream_llm(self, system, messages, send, cancel):
        def on_text(piece):
            send("delta", {"text": piece})

        def on_thinking(piece):
            send("thinking", {"n": len(piece)})

        settings = dict(self.store.settings)
        t0 = time.time()
        result = llm.stream_chat(settings, system, messages, on_text, on_thinking, cancel)
        return result, time.time() - t0

    def repair_scope(self, system, messages, answer, issues, page):
        """One self-critique pass: turn stray forward citations into ⏭ lines."""
        return guard.repair(
            self.store.settings, system, messages, answer, issues, page, self.store.handout
        )


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Pangpi/" + VERSION
    app: App = None  # type: ignore

    # -- helpers ----------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter console
        if os.environ.get("PANGBI_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _parse(self):
        parsed = urlparse(self.path)
        self.path_only = parsed.path
        self.query = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length") or 0)
        self.body = self.rfile.read(length) if length else b""

    def _authed(self) -> bool:
        tok = self.headers.get("X-Pangpi-Token") or (self.query.get("t") or [""])[0]
        return tok == self.app.token

    def _send_json(self, obj, status=200):
        data = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, ctype: str, status=200, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

    def _sse(self, event: str, data: dict) -> bool:
        payload = "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))
        try:
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            return True
        except Exception:
            return False

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        try:
            self._parse()
            if self.path_only.startswith("/static/"):
                return self._serve_static(self.path_only[len("/static/"):])
            if self.path_only in ("/", "/index.html"):
                return self._serve_static("index.html")
            if self.path_only == "/guide":
                return self._serve_guide()
            if self.path_only == "/favicon.ico":
                return self._serve_static("favicon.ico")
            if self.path_only in ("/icon-256.png", "/icon-512.png", "/apple-touch-icon.png"):
                return self._serve_static(self.path_only.lstrip("/"))
            if not self.path_only.startswith("/api/"):
                return self._send_json({"error": "not found"}, 404)
            if self.path_only == "/api/ping":
                self.app.last_ping = time.time()
                return self._send_json({"ok": True, "version": VERSION})
            if not self._authed():
                return self._send_json({"error": "unauthorized"}, 401)
            if self.path_only == "/api/state":
                return self._handle_state()
            if self.path_only == "/api/events":
                return self._handle_events()
            if self.path_only == "/api/corpus":
                return self._send_json(self.app.corpus_summary())
            if self.path_only == "/api/handout/status":
                return self._send_json(self.app.store.handout_status)
            if self.path_only == "/api/handout/outline":
                h = self.app.store.handout or {}
                return self._send_json({"outline": h.get("outline") or []})
            if self.path_only.startswith("/api/image/"):
                img = self.app.store.load_image(self.path_only.split("/")[-1])
                if not img:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_bytes(img, "image/png")
            if self.path_only == "/api/page-text":
                page = int((self.query.get("page") or ["0"])[0] or 0)
                text = handout_mod.page_text(self.app.store.handout or {"pages": []}, page)
                return self._send_json({"page": page, "text": text})
            return self._send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:
            traceback.print_exc()
            try:
                self._send_json({"error": str(exc)}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            self._parse()
            if not self.path_only.startswith("/api/"):
                return self._send_json({"error": "not found"}, 404)
            if self.path_only == "/api/ping":
                self.app.last_ping = time.time()
                return self._send_json({"ok": True})
            if not self._authed():
                return self._send_json({"error": "unauthorized"}, 401)
            route = self.path_only
            if route == "/api/settings":
                return self._handle_settings()
            if route == "/api/page":
                return self._handle_page()
            if route == "/api/handout":
                return self._handle_handout_upload()
            if route == "/api/session/reset":
                return self._handle_session_reset()
            if route == "/api/corpus/add":
                return self._handle_corpus_add()
            if route == "/api/corpus/reorder":
                return self._handle_corpus_reorder()
            if route == "/api/corpus/delete":
                return self._handle_corpus_delete()
            if route == "/api/corpus/position":
                return self._handle_corpus_position()
            if route == "/api/explain":
                return self._handle_explain()
            if route == "/api/chat":
                return self._handle_chat()
            if route == "/api/card/delete":
                payload = self._json_body()
                self.app.store.delete_card(payload.get("id") or "")
                return self._send_json({"ok": True})
            if route == "/api/card/patch":
                payload = self._json_body()
                card = self.app.store.update_card(payload.get("id") or "", **{
                    k: v for k, v in payload.items() if k in ("title", "pinned", "mode")
                })
                return self._send_json({"ok": bool(card), "card": card})
            if route == "/api/test":
                return self._handle_test()
            if route == "/api/locate":
                payload = self._json_body()
                h = self.app.store.handout
                if not h:
                    return self._send_json({"page": None, "score": 0.0})
                found = handout_mod.locate(h, payload.get("text") or "")
                found["section"] = handout_mod.section_at(h, found["page"]) if found.get("page") else None
                return self._send_json(found)
            if route == "/api/capture":
                grabbed = win32.grab_selection()
                self.app.handle_capture(
                    {"text": grabbed.get("text", ""), "image": grabbed.get("image", b"")}, "button"
                )
                return self._send_json({"ok": True, "kind": grabbed.get("kind")})
            if route == "/api/ping":
                self.app.last_ping = time.time()
                self.app.exit_at = 0.0
                return self._send_json({"ok": True})
            if route == "/api/goodbye":
                self.app.exit_at = time.time() + 8.0
                return self._send_json({"ok": True})
            if route == "/api/pin":
                ok = win32.pin_topmost(APP_TITLE, True)
                return self._send_json({"ok": ok})
            if route == "/api/reopen":
                url = "http://127.0.0.1:%d/?t=%s" % (self.app.port, self.app.token)
                profile = os.path.join(self.app.store.root, "browser")
                screen_w, _ = win32.screen_size()
                width = int(self.app.store.settings.get("width") or 440)
                win32.open_app_window(url, profile, width=width, height=980, x=screen_w - width - 24, y=32)
                threading.Thread(target=win32.pin_topmost, args=(APP_TITLE, True), daemon=True).start()
                return self._send_json({"ok": True})
            if route == "/api/shutdown":
                self._send_json({"ok": True})
                threading.Timer(0.3, lambda: os._exit(0)).start()
                return
            return self._send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:
            traceback.print_exc()
            try:
                self._send_json({"error": str(exc)}, 500)
            except Exception:
                pass

    # -- handlers ---------------------------------------------------------
    def _json_body(self) -> dict:
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception:
            return {}

    def _serve_static(self, rel: str):
        safe = re.sub(r"[^A-Za-z0-9_./-]", "", rel).lstrip("/")
        path = os.path.normpath(os.path.join(ROOT, "web", safe))
        if not path.startswith(os.path.join(ROOT, "web")) or not os.path.isfile(path):
            return self._send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as fh:
            data = fh.read()
        # 只缓存图片；html/js/css 一律不缓存，避免“新 JS 配旧 HTML”这种半更新状态
        cacheable = path.endswith((".svg", ".png", ".ico", ".woff2"))
        self._send_bytes(data, ctype, cache=cacheable)

    def _serve_guide(self):
        text = None
        # 便携版把说明书放在顶层（程序在 _internal/app），开发时就在项目根
        for cand in (
            os.path.join(ROOT, "使用说明.md"),
            os.path.join(os.path.dirname(ROOT), "使用说明.md"),
        ):
            try:
                with open(cand, "r", encoding="utf-8") as fh:
                    text = fh.read()
                break
            except OSError:
                continue
        if text is None:
            text = "使用说明.md 不存在（便携包里应该有这个文件）。"
        import html as _html

        body = _html.escape(text)
        page = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>旁批 · 使用说明</title><style>"
            "body{margin:0;background:#141518;color:#e9e7e2;"
            "font:15px/1.85 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif}"
            ".wrap{max-width:760px;margin:0 auto;padding:36px 28px 80px}"
            "pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;margin:0}"
            "a{color:#d99a5b}"
            "</style></head><body><div class=\"wrap\"><pre>" + body + "</pre></div></body></html>"
        )
        return self._send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")

    def _handle_session_reset(self):
        app = self.app
        with app.store.lock:
            app.store.corpus = corpus_mod.new_corpus()
            app.store.handout = None
            app.store.doc = 0
            app.store.page = 1
            app.store.settings["doc"] = 0
            app.store.settings["page"] = 1
        app.store.save_corpus()
        app.store.save_settings()
        try:
            os.remove(app.store.handout_path)
        except OSError:
            pass
        return self._send_json({
            "ok": True,
            "corpus": app.corpus_summary(),
            "handout": app.handout_summary(),
        })

    def _handle_state(self):
        app = self.app
        h = app.store.handout or {}
        state = {
            "version": VERSION,
            "settings": app.store.public_settings(),
            "handout": app.handout_summary(),
            "corpus": app.corpus_summary(),
            "page": app.store.page,
            "section": handout_mod.section_at(h, app.store.page) if h else None,
            "cards": app.store.cards[-40:],
            "platform": sys.platform,
            "data_dir": app.store.root,
        }
        self._send_json(state)

    def _handle_events(self):
        self._sse_start()
        q = self.app.bus.subscribe()
        try:
            self._sse("hello", {"ok": True})
            while True:
                try:
                    event = q.get(timeout=20)
                    if not self._sse(event.get("type", "message"), event):
                        break
                except queue.Empty:
                    if not self._sse("ping", {"t": time.time()}):
                        break
        except Exception:
            pass
        finally:
            self.app.bus.unsubscribe(q)

    def _handle_settings(self):
        payload = self._json_body()
        allowed = {
            "protocol", "base_url", "model", "api_key", "max_tokens", "temperature",
            "hotkey", "auto_listen", "theme", "font_size", "width", "thinking",
            "self_check",
        }
        with self.app.store.lock:
            for key, value in payload.items():
                if key in allowed:
                    self.app.store.settings[key] = value
        self.app.store.save_settings()
        self._send_json({"ok": True, "settings": self.app.store.public_settings()})

    def _handle_page(self):
        payload = self._json_body()
        try:
            page = int(payload.get("page") or 1)
        except Exception:
            page = 1
        if self.app.has_corpus():
            docs = self.app.store.corpus["docs"]
            doc_idx = int(payload.get("doc", self.app.store.doc) or 0)
            doc_idx = max(0, min(doc_idx, len(docs) - 1))
            page = max(1, min(page, corpus_mod.page_count(docs[doc_idx]) or 1))
            self.app.store.doc, self.app.store.page = doc_idx, page
            self.app.store.settings["doc"] = doc_idx
            self.app.store.settings["page"] = page
            self.app.store.save_settings()
            section = corpus_mod.section_at(docs[doc_idx], page)
            return self._send_json({"ok": True, "page": page, "doc": doc_idx, "section": section,
                                    "corpus": self.app.corpus_summary()})
        h = self.app.store.handout or {}
        if h:
            page = max(1, min(page, h.get("page_count") or 1))
        else:
            page = max(1, page)
        self.app.store.page = page
        self.app.store.settings["page"] = page
        self.app.store.save_settings()
        section = handout_mod.section_at(h, page) if h else None
        self._send_json({"ok": True, "page": page, "section": section})

    def _handle_corpus_add(self):
        from urllib.parse import unquote

        name = unquote(self.headers.get("X-Filename") or "deck.pptx")
        if not self.body:
            return self._send_json({"error": "空文件"}, 400)
        try:
            doc = corpus_mod.build_doc(name, self.body)
        except Exception as exc:
            return self._send_json({"error": "解析失败：%s" % exc}, 400)

        docs = self.app.store.corpus.setdefault("docs", [])
        current = docs[self.app.store.doc]["id"] if docs else None
        docs.append(doc)
        docs = corpus_mod.sort_docs(docs)
        self.app.store.corpus["docs"] = docs
        ids = [d["id"] for d in docs]
        self.app.store.doc = ids.index(current) if current in ids else 0
        self.app.store.settings["doc"] = self.app.store.doc
        self.app.store.save_corpus()
        self.app.store.save_settings()
        return self._send_json({
            "ok": True,
            "doc": {"id": doc["id"], "name": doc["name"], "pages": len(doc["pages"]),
                    "quality": doc.get("quality")},
            "corpus": self.app.corpus_summary(),
        })

    def _handle_corpus_reorder(self):
        payload = self._json_body()
        order = payload.get("order") or []
        docs = self.app.store.corpus.get("docs") or []
        by_id = {d["id"]: d for d in docs}
        current = docs[self.app.store.doc]["id"] if docs else None
        reordered = [by_id[i] for i in order if i in by_id]
        reordered += [d for d in docs if d["id"] not in {x["id"] for x in reordered}]
        self.app.store.corpus["docs"] = reordered
        ids = [d["id"] for d in reordered]
        self.app.store.doc = ids.index(current) if current in ids else 0
        self.app.store.settings["doc"] = self.app.store.doc
        self.app.store.save_corpus()
        self.app.store.save_settings()
        return self._send_json({"ok": True, "corpus": self.app.corpus_summary()})

    def _handle_corpus_delete(self):
        payload = self._json_body()
        target = payload.get("id") or ""
        docs = self.app.store.corpus.get("docs") or []
        current = docs[self.app.store.doc]["id"] if docs else None
        docs = [d for d in docs if d["id"] != target]
        self.app.store.corpus["docs"] = docs
        ids = [d["id"] for d in docs]
        self.app.store.doc = ids.index(current) if current in ids else max(0, min(self.app.store.doc, len(docs) - 1))
        self.app.store.save_corpus()
        return self._send_json({"ok": True, "corpus": self.app.corpus_summary()})

    def _handle_corpus_position(self):
        payload = self._json_body()
        docs = self.app.store.corpus.get("docs") or []
        if not docs:
            return self._send_json({"error": "还没有导入课件"}, 400)
        doc_idx = int(payload.get("doc", self.app.store.doc) or 0)
        doc_idx = max(0, min(doc_idx, len(docs) - 1))
        try:
            page = int(payload.get("page") or 1)
        except Exception:
            page = 1
        page = max(1, min(page, corpus_mod.page_count(docs[doc_idx]) or 1))
        self.app.store.doc, self.app.store.page = doc_idx, page
        self.app.store.settings["doc"] = doc_idx
        self.app.store.settings["page"] = page
        self.app.store.save_settings()
        return self._send_json({"ok": True, "corpus": self.app.corpus_summary()})

    def _handle_handout_upload(self):
        name = self.headers.get("X-Filename") or "handout.pdf"
        try:
            from urllib.parse import unquote

            name = unquote(name)
        except Exception:
            pass
        if not self.body or self.body[:4] != b"%PDF":
            return self._send_json({"error": "这不是一个 PDF 文件"}, 400)
        started = self.app.start_parse(self.body, name)
        self._send_json({"ok": started, "status": self.app.store.handout_status})

    def _handle_test(self):
        try:
            reply = llm.ping(self.app.store.settings)
            self._send_json({"ok": True, "reply": reply})
        except llm.LLMError as exc:
            self._send_json({"ok": False, "error": str(exc), "code": exc.code})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)})

    def _handle_explain(self):
        payload = self._json_body()
        app = self.app
        text = (payload.get("text") or "").strip()
        mode = payload.get("mode") or "explain"
        hint_level = int(payload.get("hint_level") or 1)
        image_id = payload.get("image_id") or ""
        page = payload.get("page")
        doc_index = payload.get("doc")
        if not image_id and payload.get("image"):
            try:
                image_id = app.store.save_image(base64.b64decode(payload["image"]))
            except Exception:
                image_id = ""
        if not text and not image_id:
            return self._send_json({"error": "没有内容"}, 400)

        image = app.store.load_image(image_id) if image_id else None

        # 结构判断优先；落在灰色地带时让模型看一眼（只花半秒）。
        # 判不出来也按题处理——多问一次只多一次点击，剧透一次就白读了。
        verdict = exercise.judge(text) if text and not image_id else "prose"
        if verdict == "ambiguous":
            decided = None
            if app.store.settings.get("api_key"):
                decided = llm.classify_exercise(app.store.settings, text)
            verdict = "exercise" if decided is not False else "prose"
        is_exercise = verdict == "exercise"

        # 习题先问，不直接开讲：只翻译 / 给提示 / 讲解
        if mode == "auto" and is_exercise and text and not image_id:
            section = ""
            doc_name = ""
            if app.has_corpus():
                docs = app.store.corpus["docs"]
                doc_index = app.store.doc if doc_index is None else int(doc_index)
                found = corpus_mod.locate(app.store.corpus, text)
                if found.get("score", 0) >= 0.6 and found.get("doc") is not None:
                    doc_index, page = found["doc"], found["page"]
                ctx = corpus_mod.context(app.store.corpus, doc_index, int(page or app.store.page or 1))
                doc_index, page = ctx["doc_index"], ctx["page"]
                section, doc_name = ctx.get("section") or "", ctx.get("name") or ""
            else:
                if app.store.handout:
                    found = handout_mod.locate(app.store.handout, text)
                    if found.get("score", 0) >= 0.6 and found.get("page"):
                        page = found["page"]
                page = int(page or app.store.page or 1)
                section = (handout_mod.section_at(app.store.handout, page) or {}).get("title") if app.store.handout else ""
            card = {
                "id": uuid.uuid4().hex[:12],
                "ts": time.time() * 1000,
                "selection": text,
                "mode": "ask",
                "status": "ask",
                "exercise": True,
                "page": page,
                "doc": doc_index if doc_index is not None else 0,
                "doc_name": doc_name,
                "section": section,
                "answer": "",
            }
            self._sse_start()
            self._sse("meta", {"card": card, "page": page})
            self._sse("ask", {
                "card": card,
                "modes": ["translate", "hint", "explain"],
                "has_latin": bool(re.search(r"[A-Za-z]{3,}", text)),
            })
            return

        if mode == "auto":
            mode = "explain"
        is_formula = bool(text) and not image_id and formula.looks_like_formula(text)
        section = ""
        doc_name = ""

        if app.has_corpus():
            docs = app.store.corpus["docs"]
            doc_index = app.store.doc if doc_index is None else int(doc_index)
            doc_index = max(0, min(doc_index, len(docs) - 1))
            # a confident hit in the corpus beats the position the UI believes
            if text:
                found = corpus_mod.locate(app.store.corpus, text)
                if found.get("score", 0) >= 0.6 and found.get("doc") is not None:
                    doc_index, page = found["doc"], found["page"]
            ctx = corpus_mod.context(app.store.corpus, doc_index, int(page or app.store.page or 1))
            doc_index, page = ctx["doc_index"], ctx["page"]
            section = ctx.get("section") or ""
            doc_name = ctx.get("name") or ""
            if (doc_index, page) != (app.store.doc, app.store.page):
                app.store.doc, app.store.page = doc_index, page
                app.store.settings["doc"] = doc_index
                app.store.settings["page"] = page
                app.store.save_settings()
            system, messages = prompts.build_messages_multi(
                ctx, text, mode=mode, hint_level=hint_level,
                image=image, exercise=is_exercise, formula_suspect=is_formula,
            )
        else:
            # legacy single-handout path
            if text and app.store.handout:
                found = handout_mod.locate(app.store.handout, text)
                if found.get("score", 0) >= 0.6 and found.get("page"):
                    page = found["page"]
            page = int(page or app.store.page or 1)
            if app.store.handout and page != app.store.page:
                app.store.page = page
                app.store.settings["page"] = page
                app.store.save_settings()
            section = (handout_mod.section_at(app.store.handout, page) or {}).get("title") if app.store.handout else ""
            system, messages = prompts.build_messages(
                app.store.handout, page, text, mode=mode, hint_level=hint_level,
                image=image, exercise=is_exercise, formula_suspect=is_formula,
            )

        card = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time() * 1000,
            "selection": text,
            "mode": mode,
            "parent_id": payload.get("parent_id") or "",
            "hint_level": hint_level if mode == "hint" else 0,
            "page": page,
            "doc": doc_index if doc_index is not None else 0,
            "doc_name": doc_name,
            "section": section,
            "image_id": image_id,
            "answer": "",
            "exercise": is_exercise,
            "formula": is_formula,
            "status": "streaming",
        }

        self._sse_start()
        cancel = threading.Event()
        self._sse("meta", {"card": card, "page": page, "has_handout": bool(app.store.handout)})
        started = time.time()
        try:
            result, elapsed = app.stream_llm(system, messages, self._sse, cancel)
            card["answer"] = result.text.strip()
            if result.stop_reason in ("max_tokens", "length"):
                card["answer"] += (
                    "\n\n> 回答达到长度上限被截断。可在设置里把「回答长度上限」调大。"
                )

            # Self-check: every forward reference must live inside a ⏭ line.
            if app.store.settings.get("self_check", True) and mode != "chat":
                issues = guard.check_scope(card["answer"], page, app.store.handout)
                if issues:
                    self._sse("notice", {"text": "自查：正文出现了后文引用（%s），正在修正…" % "、".join(issues)})
                    fixed = app.repair_scope(system, messages, card["answer"], issues, page)
                    if fixed:
                        card["answer"] = fixed
                        card["repaired"] = True
                        card["issues"] = issues
                        self._sse("replace", {"text": fixed, "issues": issues})
                    else:
                        self._sse("note", {"text": "自查发现正文引用了后文，但自动修正没有成功，请以「依据」为准。"})

            card["thinking"] = result.thinking[:4000]
            card["status"] = "done"
            card["elapsed"] = round(elapsed, 2)
            card["usage"] = {
                "input": result.usage.input_tokens,
                "output": result.usage.output_tokens,
                "cache": result.usage.cache_read,
            }
            app.store.add_card(card)
            self._sse("done", {"card": card, "elapsed": round(elapsed, 2)})
        except llm.LLMError as exc:
            card["status"] = "error"
            card["error"] = str(exc)
            app.store.add_card(card)
            self._sse("error", {"card": card, "message": str(exc), "code": exc.code})
        except (BrokenPipeError, ConnectionResetError):
            cancel.set()
        except Exception as exc:
            traceback.print_exc()
            self._sse("error", {"card": card, "message": "服务端错误：%s" % exc})

    def _handle_chat(self):
        payload = self._json_body()
        app = self.app
        card_id = payload.get("card_id") or ""
        question = (payload.get("question") or "").strip()
        if not question:
            return self._send_json({"error": "问题为空"}, 400)
        card = app.store.get_card(card_id)
        if not card:
            return self._send_json({"error": "找不到这张卡片"}, 404)
        page = int(payload.get("page") or card.get("page") or app.store.page or 1)
        system, messages = prompts.build_chat_messages(app.store.handout, page, {
            "selection": card.get("selection"),
            "answer": card.get("answer"),
            "question": question,
        })

        self._sse_start()
        self._sse("meta", {"card_id": card_id})
        try:
            result, elapsed = app.stream_llm(system, messages, self._sse, threading.Event())
            msg = {
                "id": uuid.uuid4().hex[:12],
                "role": "assistant",
                "text": result.text.strip(),
                "ts": time.time() * 1000,
            }
            with app.store.lock:
                card.setdefault("thread", []).append(
                    {"id": uuid.uuid4().hex[:10], "role": "user", "text": question, "ts": time.time() * 1000}
                )
                card["thread"].append(msg)
            app.store.save_cards()
            self._sse("done", {"card_id": card_id, "message": msg, "elapsed": round(elapsed, 2)})
        except llm.LLMError as exc:
            self._sse("error", {"card_id": card_id, "message": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            traceback.print_exc()
            self._sse("error", {"card_id": card_id, "message": "服务端错误：%s" % exc})


# --------------------------------------------------------------------------
# boot
# --------------------------------------------------------------------------


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def existing_instance(data_dir: str) -> int | None:
    lock = os.path.join(data_dir, "server.json")
    if not os.path.exists(lock):
        return None
    try:
        with open(lock, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        port = int(info.get("port") or 0)
        token = info.get("token") or ""
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/ping?t=%s" % (port, token), method="GET"
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return port
    except Exception:
        return None
    return None


def browser_profile_dir(data_dir: str) -> str:
    """Keep the browser profile outside the app folder.

    Edge keeps a few processes alive for a while after the window closes and
    holds files under its profile; leaving that inside 旁批/data makes the
    whole folder undeletable.  %LOCALAPPDATA% is the normal place for it.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "Pangpi", "browser")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        return os.path.join(data_dir, "browser")


def wait_ready(port: int, timeout: float = 8.0) -> bool:
    """Block until the local HTTP server answers /api/ping."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def open_window(url: str, data_dir: str, width: int) -> bool:
    """Launch the app window and confirm it actually appeared (retry once)."""
    profile = browser_profile_dir(data_dir)
    screen_w, _ = win32.screen_size()
    x = max(0, screen_w - width - 24)
    for attempt in (1, 2):
        prof = profile if attempt == 1 else profile + "-retry"
        win32.open_app_window(url, prof, width=width, height=980, x=x, y=32)
        for _ in range(38):
            time.sleep(0.4)
            if win32.has_window(APP_TITLE):
                threading.Thread(target=win32.pin_topmost, args=(APP_TITLE, True), daemon=True).start()
                print("[window] opened on attempt %d" % attempt, flush=True)
                return True
        print("[window] attempt %d: no window yet" % attempt, flush=True)
    return False


def main():
    parser = argparse.ArgumentParser(description="旁批 · 讲义伴读")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-window", action="store_true", help="do not open a browser window")
    parser.add_argument("--no-hotkey", action="store_true")
    parser.add_argument("--keep-alive", action="store_true", help="never exit on heartbeat timeout")
    parser.add_argument("--new", action="store_true", help="start even if an instance is running")
    args = parser.parse_args()

    data_dir = args.data_dir or pick_data_dir(ROOT)
    if not args.new:
        port = existing_instance(data_dir)
        if port:
            if win32.focus_window(APP_TITLE):
                print("已在运行：http://127.0.0.1:%d/" % port)
                return 0
            # The service is alive but its window is gone: reopen it instead of
            # silently doing nothing.
            try:
                with open(os.path.join(data_dir, "server.json"), "r", encoding="utf-8") as fh:
                    token = json.load(fh).get("token") or ""
                settings = Store(data_dir)
                url = "http://127.0.0.1:%d/?t=%s" % (port, token)
                width = int(settings.settings.get("width") or 440)
                open_window(url, data_dir, width)
                print("已重新打开窗口：%s" % url)
            except Exception:
                print("已在运行：http://127.0.0.1:%d/" % port)
            return 0

    app = App(data_dir)
    app.start_watcher()
    if not args.no_hotkey:
        app.start_hotkey()

    Handler.app = app
    port = args.port or find_free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    app.port = port
    app.server = httpd

    url = "http://127.0.0.1:%d/?t=%s" % (port, app.token)
    info_path = os.path.join(data_dir, "server.json")
    with open(info_path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"port": port, "pid": os.getpid(), "token": app.token, "ts": time.time()}, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(info_path + ".tmp", info_path)

    # Serve first, open the window only once the port really answers.  Opening
    # the browser earlier leaves it on a "can't reach this page" screen that
    # never retries — the reason the window looked dead until "重开窗口".
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    ready = wait_ready(port)
    print("[boot] 服务就绪：%s" % ready, flush=True)

    if not args.no_window:
        width = int(app.store.settings.get("width") or 440)
        app.window_opened = open_window(url, data_dir, width)
        if not app.window_opened:
            print("[window] 两次都没检测到窗口，请手动打开：%s" % url, flush=True)

    def watchdog():
        while True:
            time.sleep(1.0)
            if args.keep_alive or not app.window_opened:
                continue
            # 窗口关闭后页面会发 /api/goodbye；8 秒内没有新的 ping 就退出
            if app.exit_at and time.time() > app.exit_at:
                try:
                    os.remove(os.path.join(data_dir, "server.json"))
                except Exception:
                    pass
                os._exit(0)
            if time.time() - app.last_ping > 100:
                try:
                    os.remove(os.path.join(data_dir, "server.json"))
                except Exception:
                    pass
                os._exit(0)

    threading.Thread(target=watchdog, daemon=True).start()

    print("旁批 v%s 已启动：%s" % (VERSION, url))
    print("数据目录：%s" % data_dir)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(os.path.join(data_dir, "server.json"))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
