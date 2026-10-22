# -*- coding: utf-8 -*-
"""Thin Win32 layer: clipboard, global hotkey, window pinning, browser launch.

Everything here is best-effort and degrades to a no-op on non-Windows or when a
call fails, so the server keeps working (paste-in UI still usable).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import time
import zlib

IS_WINDOWS = os.name == "nt"

user32 = ctypes.windll.user32 if IS_WINDOWS else None
kernel32 = ctypes.windll.kernel32 if IS_WINDOWS else None

CF_TEXT = 1
CF_DIB = 8
CF_UNICODETEXT = 13
CF_DIBV5 = 17
GMEM_MOVEABLE = 0x0002

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


# --------------------------------------------------------------------------
# clipboard
# --------------------------------------------------------------------------

if IS_WINDOWS:
    user32.OpenClipboard.argtypes = [wt.HWND]
    user32.OpenClipboard.restype = wt.BOOL
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = wt.HANDLE
    user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    user32.SetClipboardData.restype = wt.HANDLE
    user32.GetClipboardSequenceNumber.restype = wt.DWORD
    kernel32.GlobalLock.argtypes = [wt.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
    kernel32.GlobalUnlock.restype = wt.BOOL
    kernel32.GlobalSize.argtypes = [wt.HANDLE]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wt.HGLOBAL
    kernel32.GlobalFree.argtypes = [wt.HGLOBAL]
    kernel32.GlobalFree.restype = wt.HGLOBAL
    user32.EmptyClipboard.restype = wt.BOOL
    user32.CloseClipboard.restype = wt.BOOL
    user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    user32.SetClipboardData.restype = wt.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wt.UINT
    user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
    user32.IsClipboardFormatAvailable.restype = wt.BOOL


def clipboard_sequence() -> int:
    if not IS_WINDOWS:
        return 0
    try:
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def _open_clipboard(retries: int = 8) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def read_clipboard(want_image: bool = True) -> dict:
    """Return {'kind': 'text'|'image'|'empty', 'text': str, 'image': bytes(png)}."""
    out = {"kind": "empty", "text": "", "image": b"", "seq": clipboard_sequence()}
    if not IS_WINDOWS:
        return out
    if not _open_clipboard():
        return out
    try:
        if want_image:
            png_fmt = user32.RegisterClipboardFormatW("PNG")
            if png_fmt and user32.IsClipboardFormatAvailable(png_fmt):
                data = _read_handle(png_fmt)
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    out["kind"] = "image"
                    out["image"] = data
                    return out
            if user32.IsClipboardFormatAvailable(CF_DIB):
                png = _dib_to_png(_read_handle(CF_DIB))
                if png:
                    out["kind"] = "image"
                    out["image"] = png
                    return out
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            raw = _read_handle(CF_UNICODETEXT)
            if raw:
                text = raw.decode("utf-16-le", "ignore").split("\x00")[0]
                text = text.replace("\r\n", "\n").strip()
                if text:
                    out["kind"] = "text"
                    out["text"] = text
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
    return out


def _read_handle(fmt: int) -> bytes:
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return b""
    size = kernel32.GlobalSize(handle)
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return b""
    try:
        return ctypes.string_at(ptr, int(size)) if size else b""
    finally:
        kernel32.GlobalUnlock(handle)


def write_clipboard_text(text: str) -> bool:
    if not IS_WINDOWS:
        return False
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass


# --------------------------------------------------------------------------
# DIB -> PNG (no third-party dependency)
# --------------------------------------------------------------------------


def _dib_to_png(dib: bytes) -> bytes:
    try:
        return _dib_to_png_inner(dib)
    except Exception:
        return b""


def _dib_to_png_inner(dib: bytes) -> bytes:
    if len(dib) < 40:
        return b""
    (bi_size, width, height, planes, bpp, compression, _size, _x, _y, _used, _imp) = struct.unpack_from(
        "<IiiHHIIiiII", dib, 0
    )
    if bi_size < 40 or width <= 0 or height == 0 or compression not in (0, 3):
        return b""
    bottom_up = height > 0
    height = abs(height)
    palette = b""
    offset = bi_size
    if bpp <= 8:
        ncolors = _used or (1 << bpp)
        palette = dib[offset : offset + ncolors * 4]
        offset += ncolors * 4
    stride = ((width * bpp + 31) // 32) * 4
    need = offset + stride * height
    if len(dib) < need:
        return b""

    rows = []
    for y in range(height):
        src_y = height - 1 - y if bottom_up else y
        start = offset + src_y * stride
        row = dib[start : start + stride]
        if bpp == 32:
            bgra = row[: width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3] = bgra[2::4]
            rgb[1::3] = bgra[1::4]
            rgb[2::3] = bgra[0::4]
        elif bpp == 24:
            bgr = row[: width * 3]
            rgb = bytearray(width * 3)
            rgb[0::3] = bgr[2::3]
            rgb[1::3] = bgr[1::3]
            rgb[2::3] = bgr[0::3]
        elif bpp == 8:
            idx = row[:width]
            rgb = bytearray(width * 3)
            for x, i in enumerate(idx):
                o = i * 4
                if o + 2 < len(palette):
                    rgb[x * 3] = palette[o + 2]
                    rgb[x * 3 + 1] = palette[o + 1]
                    rgb[x * 3 + 2] = palette[o]
        else:
            return b""
        rows.append(bytes(rgb))
    return _encode_png(rows, width, height, max_dim=1600)


def _downsample(rows, width, height, step):
    if step <= 1:
        return rows, width, height
    new_w = max(1, width // step)
    new_rows = []
    for y in range(0, height, step):
        row = rows[y]
        out = bytearray(new_w * 3)
        for x in range(new_w):
            sx = x * step * 3
            out[x * 3 : x * 3 + 3] = row[sx : sx + 3]
        new_rows.append(bytes(out))
    return new_rows, new_w, len(new_rows)


def _encode_png(rows, width, height, max_dim=1600) -> bytes:
    step = 1
    while max(width // step, height // step) > max_dim:
        step += 1
    if step > 1:
        rows, width, height = _downsample(rows, width, height, step)

    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------
# input / hotkeys
# --------------------------------------------------------------------------

VK_CONTROL = 0x11
VK_C = 0x43
VK_SHIFT = 0x10
VK_MENU = 0x12


def send_copy() -> None:
    """Synthesize Ctrl+C into the foreground window."""
    if not IS_WINDOWS:
        return
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_C, 0, 2, 0)
    user32.keybd_event(VK_CONTROL, 0, 2, 0)


def grab_selection(timeout: float = 1.2) -> dict:
    """Send Ctrl+C, wait for the clipboard to change, return its content."""
    before = clipboard_sequence()
    send_copy()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.05)
        if clipboard_sequence() != before:
            time.sleep(0.08)
            return read_clipboard()
    return {"kind": "empty", "text": "", "image": b"", "seq": before}


class HotkeyListener:
    """A daemon thread running a Win32 message loop for global hotkeys."""

    def __init__(self):
        self._thread = None
        self._ready = False

    def start(self, spec: str, callback) -> bool:
        if not IS_WINDOWS:
            return False
        mods, vk = parse_hotkey(spec)
        if vk is None:
            return False

        def run():
            try:
                ok = user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)
                self._ready = bool(ok)
                if not ok:
                    return
                msg = wt.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY:
                        try:
                            callback()
                        except Exception:
                            pass
            finally:
                try:
                    user32.UnregisterHotKey(None, 1)
                except Exception:
                    pass

        import threading

        self._thread = threading.Thread(target=run, name="hotkey", daemon=True)
        self._thread.start()
        time.sleep(0.15)
        return self._ready


def parse_hotkey(spec: str):
    mods = 0
    parts = [p.strip().lower() for p in (spec or "").replace("+", " ").split() if p.strip()]
    vk = None
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "meta"):
            mods |= MOD_WIN
        elif len(p) == 1:
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x6F + int(p[1:])   # VK_F1 = 0x70
    return mods, vk


# --------------------------------------------------------------------------
# windows
# --------------------------------------------------------------------------


def _window_texts():
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def has_window(title_part: str) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return any(title_part in title for _hwnd, title in _window_texts())
    except Exception:
        return False


def pin_topmost(title_part: str, topmost: bool = True) -> bool:
    if not IS_WINDOWS:
        return False
    target = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    for _ in range(40):
        for hwnd, title in _window_texts():
            if title_part in title:
                user32.SetWindowPos(
                    hwnd, target, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
                return True
        time.sleep(0.25)
    return False


def focus_window(title_part: str) -> bool:
    if not IS_WINDOWS:
        return False
    for hwnd, title in _window_texts():
        if title_part in title:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return True
    return False


BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str | None:
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    return None


def open_app_window(url: str, profile_dir: str, width=440, height=980, x=None, y=40):
    """Open the UI in a chrome-less app window.  Returns the Popen or None."""
    exe = find_browser()
    if exe is None:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            pass
        return None
    args = [
        exe,
        "--app=" + url,
        "--user-data-dir=" + profile_dir,
        "--window-size=%d,%d" % (width, height),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-mode",
        "--no-default-browser-check",
    ]
    if x is not None:
        args.append("--window-position=%d,%d" % (x, y))
    flags = 0x00000008  # DETACHED_PROCESS
    try:
        return subprocess.Popen(args, close_fds=True, creationflags=flags)
    except Exception:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            pass
        return None


def screen_size():
    if not IS_WINDOWS:
        return (1920, 1080)
    try:
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        return (1920, 1080)
