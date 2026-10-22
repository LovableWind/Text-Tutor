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
import guard  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
import win32  # noqa: E402

VERSION = "1.0.0"
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
        self.img_dir = os.path.join(root, "img")
        os.makedirs(self.img_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = self._load_settings()
        self.handout = handout_mod.load_handout(self.handout_path)
        self.cards = self._load_cards()
        self.page = int(self.settings.get("page") or 1)
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
            if self.path_only == "/favicon.ico":
                return self._serve_static("favicon.svg")
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
        self._send_bytes(data, ctype, cache=not path.endswith("index.html"))

    def _handle_state(self):
        app = self.app
        h = app.store.handout or {}
        state = {
            "version": VERSION,
            "settings": app.store.public_settings(),
            "handout": app.handout_summary(),
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
        if not image_id and payload.get("image"):
            try:
                image_id = app.store.save_image(base64.b64decode(payload["image"]))
            except Exception:
                image_id = ""
        # A confident match in the handout beats whatever page the UI thinks it is on.
        if text and app.store.handout:
            found = handout_mod.locate(app.store.handout, text)
            if found.get("score", 0) >= 0.6 and found.get("page"):
                page = found["page"]
        page = int(page or app.store.page or 1)
        if app.store.handout and page != app.store.page:
            app.store.page = page
            app.store.settings["page"] = page
            app.store.save_settings()

        if not text and not image_id:
            return self._send_json({"error": "没有内容"}, 400)

        image = app.store.load_image(image_id) if image_id else None

        is_exercise = prompts.looks_like_exercise(text)
        system, messages = prompts.build_messages(
            app.store.handout, page, text, mode=mode, hint_level=hint_level,
            image=image, exercise=is_exercise,
        )
        card = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time() * 1000,
            "selection": text,
            "mode": mode,
            "parent_id": payload.get("parent_id") or "",
            "hint_level": hint_level if mode == "hint" else 0,
            "page": page,
            "section": (handout_mod.section_at(app.store.handout, page) or {}).get("title") if app.store.handout else "",
            "image_id": image_id,
            "answer": "",
            "exercise": prompts.looks_like_exercise(text),
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
                screen_w, _ = win32.screen_size()
                win32.open_app_window(url, os.path.join(data_dir, "browser"),
                                      width=width, height=980, x=screen_w - width - 24, y=32)
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
    with open(os.path.join(data_dir, "server.json"), "w", encoding="utf-8") as fh:
        json.dump({"port": port, "pid": os.getpid(), "token": app.token, "ts": time.time()}, fh)

    if not args.no_window:
        profile = os.path.join(data_dir, "browser")
        screen_w, _ = win32.screen_size()
        width = int(app.store.settings.get("width") or 440)
        win32.open_app_window(url, profile, width=width, height=980, x=screen_w - width - 24, y=32)
        app.window_opened = True

        def pin():
            win32.pin_topmost(APP_TITLE, True)

        threading.Thread(target=pin, daemon=True).start()

    def watchdog():
        while True:
            time.sleep(15)
            if args.keep_alive or not app.window_opened:
                continue
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
        httpd.serve_forever()
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
