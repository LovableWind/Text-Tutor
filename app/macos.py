# -*- coding: utf-8 -*-
"""macOS 后端：和 win32.py 提供同一组接口，全部只用标准库 + 系统命令。

能等价做到的：剪贴板读写（文本 / 截图）、Cmd+C 取词、拉起 Chrome 应用窗口、屏幕尺寸。
做不到的：全局热键（需要装辅助工具）、窗口置顶（Chrome 应用窗口没有这个接口）。
这两项在这边退化为空实现，server 会自动跳过。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time

IS_WINDOWS = False
IS_MACOS = True

APP_TITLE_DEFAULT = "旁批"

_cache = {"seq": 0, "digest": None, "text": "", "image": b""}
_last_profile = None


# ------------------------------------------------------------------ 基础执行
def _run(args, data=None, timeout=6.0):
    try:
        return subprocess.run(
            args,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except Exception:
        return None


def _osascript(script: str, timeout=6.0):
    res = _run(["osascript", "-e", script], timeout=timeout)
    if res is None or res.returncode != 0:
        return None
    return (res.stdout or b"").decode("utf-8", "replace").strip()


# ------------------------------------------------------------------ 剪贴板
def _read_text() -> str:
    res = _run(["pbpaste"])
    if res is None or res.returncode != 0:
        return ""
    return (res.stdout or b"").decode("utf-8", "replace")


def _tiff_to_png(data: bytes):
    """剪贴板里只有 TIFF 时，借 sips 转一次。"""
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.tiff")
            dst = os.path.join(tmp, "out.png")
            with open(src, "wb") as fh:
                fh.write(data)
            res = _run(["sips", "-s", "format", "png", src, "--out", dst], timeout=8)
            if res is None or res.returncode != 0 or not os.path.exists(dst):
                return b""
            with open(dst, "rb") as fh:
                return fh.read()
    except Exception:
        return b""


def _read_image() -> bytes:
    res = _run(["pbpaste", "-Prefer", "png"])
    data = (res.stdout if res and res.returncode == 0 else b"") or b""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return _tiff_to_png(data)
    return b""


def _refresh():
    text = _read_text()
    image = b"" if text.strip() else _read_image()
    digest = hashlib.sha1(text.encode("utf-8") + b"\x00" + image).hexdigest()
    if digest != _cache["digest"]:
        _cache["seq"] += 1
        _cache["digest"] = digest
        _cache["text"] = text
        _cache["image"] = image
    return _cache["seq"]


def clipboard_sequence() -> int:
    return _refresh()


def read_clipboard():
    if _cache["digest"] is None:
        _refresh()
    return _cache["text"], _cache["image"]


def write_clipboard_text(text: str) -> bool:
    res = _run(["pbcopy"], data=(text or "").encode("utf-8"))
    return bool(res is not None and res.returncode == 0)


def send_copy() -> bool:
    """模拟 Cmd+C。需要给终端/旁批开“辅助功能”权限，否则静默失败。"""
    out = _osascript('tell application "System Events" to keystroke "c" using command down')
    return out is not None


def grab_selection():
    """复制当前选中的内容并读出来。"""
    send_copy()
    time.sleep(0.25)
    _refresh()
    return _cache["text"], _cache["image"]


# ------------------------------------------------------------------ 热键
def parse_hotkey(spec: str):
    return 0, None


class HotkeyListener:
    """macOS 上不做全局热键：需要额外的辅助工具，不值得引入。"""

    def start(self, spec: str, callback) -> bool:
        return False

    def stop(self):
        return None


# ------------------------------------------------------------------ 窗口
def _app_path(name: str):
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        path = os.path.join(base, name + ".app")
        if os.path.isdir(path):
            return path
    return None


BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi")


def find_browser():
    for name in BROWSERS:
        if _app_path(name):
            return name
    return None


def browser_profile_dir(data_dir: str) -> str:
    base = os.path.join(os.path.expanduser("~/Library/Application Support"), "Pangpi")
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return data_dir


def open_app_window(url: str, profile_dir: str, width=440, height=980, x=None, y=32):
    """Chrome 系的 --app 窗口在 macOS 上同样可用。"""
    global _last_profile
    app = find_browser()
    if not app:
        _run(["open", url])
        return None
    try:
        os.makedirs(profile_dir, exist_ok=True)
    except Exception:
        pass
    _last_profile = profile_dir
    args = [
        "open", "-na", app, "--args",
        "--app=" + url,
        "--user-data-dir=" + profile_dir,
        "--window-size=%d,%d" % (width, height),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-mode",
    ]
    return _run(args, timeout=10)


def has_window(title: str = "") -> bool:
    """没有可用的窗口枚举 API，退而检查带我们 profile 的浏览器进程是否还在。"""
    if not _last_profile:
        return False
    res = _run(["pgrep", "-f", _last_profile], timeout=4)
    return bool(res is not None and res.returncode == 0 and (res.stdout or b"").strip())


def pin_topmost(title: str = "", on: bool = True) -> bool:
    """Chrome 应用窗口在 macOS 上没有置顶接口。"""
    return False


def focus_window(title: str = "") -> bool:
    app = find_browser()
    if not app:
        return False
    return _osascript('tell application "%s" to activate' % app) is not None


def screen_size():
    out = _osascript('tell application "Finder" to get bounds of window of desktop')
    if out:
        try:
            parts = [int(p.strip()) for p in out.split(",")]
            if len(parts) == 4:
                return parts[2], parts[3]
        except Exception:
            pass
    return 1440, 900


def bring_to_front(url: str):
    return focus_window()
