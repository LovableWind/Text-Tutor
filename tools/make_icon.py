# -*- coding: utf-8 -*-
"""生成旁批的图标：PNG 多尺寸 + Windows .ico。

没有用任何图形库——画布、抗锯齿、PNG 编码都是手写的，这样打包时不需要
额外依赖，也能在只有标准库的运行时里跑。

    python tools/make_icon.py
"""

from __future__ import annotations

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

BG = (29, 31, 36, 255)       # 深灰底
PAGE = (243, 238, 228, 255)  # 纸色
INK = (43, 42, 38, 255)      # 墨色
ACCENT = (217, 154, 91, 255)  # 赭石
SHADOW = (0, 0, 0, 60)


class Canvas:
    """超采样画布：先在 N 倍尺寸上画，最后求平均。"""

    def __init__(self, size: int, scale: int = 4):
        self.size = size
        self.scale = scale
        self.w = size * scale
        self.buf = [[0, 0, 0, 0] for _ in range(self.w * self.w)]

    def _blend(self, x: int, y: int, color):
        if x < 0 or y < 0 or x >= self.w or y >= self.w:
            return
        i = y * self.w + x
        dst = self.buf[i]
        a = color[3] / 255.0
        if a >= 1.0:
            dst[0], dst[1], dst[2], dst[3] = color
            return
        dst[0] = int(color[0] * a + dst[0] * (1 - a))
        dst[1] = int(color[1] * a + dst[1] * (1 - a))
        dst[2] = int(color[2] * a + dst[2] * (1 - a))
        dst[3] = max(dst[3], color[3])

    def round_rect(self, x0, y0, x1, y1, r, color):
        s = self.scale
        x0, y0, x1, y1, r = (v * s for v in (x0, y0, x1, y1, r))
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1):
                cx = min(max(x, x0 + r), x1 - r)
                cy = min(max(y, y0 + r), y1 - r)
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self._blend(x, y, color)

    def circle(self, cx, cy, r, color):
        s = self.scale
        cx, cy, r = cx * s, cy * s, r * s
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self._blend(x, y, color)

    def line(self, x0, y0, x1, y1, w, color):
        """两端圆头的粗线。"""
        s = self.scale
        x0, y0, x1, y1, w = (v * s for v in (x0, y0, x1, y1, w))
        hw = w / 2.0
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy or 1.0
        for y in range(int(min(y0, y1) - hw) - 1, int(max(y0, y1) + hw) + 2):
            for x in range(int(min(x0, x1) - hw) - 1, int(max(x0, x1) + hw) + 2):
                t = ((x - x0) * dx + (y - y0) * dy) / length2
                t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                px, py = x0 + t * dx, y0 + t * dy
                if (x - px) ** 2 + (y - py) ** 2 <= hw * hw:
                    self._blend(x, y, color)

    def render(self) -> bytes:
        """降采样成 size×size 的 RGBA。"""
        s = self.scale
        out = bytearray()
        w = self.size
        n = s * s
        for y in range(w):
            for x in range(w):
                r = g = b = a = 0
                for dy in range(s):
                    row = (y * s + dy) * self.w
                    for dx in range(s):
                        p = self.buf[row + x * s + dx]
                        r += p[0]
                        g += p[1]
                        b += p[2]
                        a += p[3]
                out += bytes((r // n, g // n, b // n, a // n))
        return bytes(out)


def draw(size: int) -> bytes:
    c = Canvas(size)
    u = size / 512.0  # 以 512 为设计基准

    def S(v):
        return v * u

    # 底板
    c.round_rect(S(16), S(16), S(496), S(496), S(112), BG)
    # 纸张（先垫一层半透明暗色当投影）
    c.round_rect(S(112), S(124), S(404), S(432), S(26), SHADOW)
    c.round_rect(S(104), S(112), S(408), S(424), S(26), PAGE)
    # 页边竖线
    c.line(S(152), S(158), S(152), S(376), S(8), ACCENT)
    # 正文行（留出右侧页边空白）
    # 第二行先铺一条半透明赭石高亮，像荧光笔划过的“正在讲的那句”
    c.round_rect(S(178), S(202), S(360), S(232), S(12), (217, 154, 91, 110))
    for y, length in ((166, 180), (217, 150), (268, 168), (318, 96)):
        c.line(S(190), S(y), S(190 + length), S(y), S(16), INK)
    return c.render()


def png(data: bytes, size: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b""
    stride = size * 4
    for y in range(size):
        raw += b"\x00" + data[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico(pngs: list) -> bytes:
    """PNG-in-ICO：Vista 以后 Windows 直接支持。"""
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    payload = b""
    for size, data in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    sizes = [256, 128, 64, 48, 32, 16]
    made = []
    for size in sizes:
        data = draw(size)
        path = os.path.join(WEB, "icon-%d.png" % size)
        with open(path, "wb") as fh:
            fh.write(png(data, size))
        made.append((size, png(data, size)))
        print("wrote web/icon-%d.png" % size)

    with open(os.path.join(WEB, "favicon.ico"), "wb") as fh:
        fh.write(ico(made))
    print("wrote web/favicon.ico")

    big = draw(512)
    with open(os.path.join(WEB, "icon-512.png"), "wb") as fh:
        fh.write(png(big, 512))
    print("wrote web/icon-512.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
