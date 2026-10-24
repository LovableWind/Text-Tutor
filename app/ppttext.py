# -*- coding: utf-8 -*-
"""旧版 .ppt（PowerPoint 97-2003）文字提取，纯标准库。

.ppt 是 OLE 复合文档（CFB），幻灯片内容在 "PowerPoint Document" 流里，
由一层层定长记录组成。这里只做两件事：找到文本记录、按幻灯片切开。

排版、图片、公式对象一概不取——和 .pptx 一样，只提供"这一页在讲什么"的上下文。
"""

from __future__ import annotations

import struct
import zlib

CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC

# PPT 记录类型
RT_DOCUMENT = 0x03E8
RT_SLIDE = 0x03EE
RT_SLIDE_PERSIST = 0x03F3
RT_SLIDE_LIST_WITH_TEXT = 0x0FF0
RT_TEXT_CHARS = 0x0FA0
RT_TEXT_BYTES = 0x0FA8
RT_TEXT_HEADER = 0x0F9E


class PptError(Exception):
    pass


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


class CompoundFile:
    """够用的 CFB 读取器：只有目录 + 两条读取路径。"""

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != CFB_MAGIC:
            raise PptError("不是有效的 .ppt 文件（缺少 OLE 复合文档头）")
        self.data = data
        self.sector_size = 1 << _u16(data, 30)
        self.mini_size = 1 << _u16(data, 32)
        self.num_fat = _u32(data, 44)
        self.dir_start = _u32(data, 48)
        self.mini_cutoff = _u32(data, 56)
        self.minifat_start = _u32(data, 60)
        self.num_minifat = _u32(data, 64)
        self.difat_start = _u32(data, 68)
        self.num_difat = _u32(data, 72)
        self.fat = self._read_fat()
        self.entries = self._read_directory()
        root = self.entries[0] if self.entries else None
        self.mini_stream = b""
        if root and root["start"] not in (ENDOFCHAIN, FREESECT) and root["size"]:
            self.mini_stream = self._read_chain(root["start"], root["size"], mini=False)
        self.minifat = self._read_minifat()

    # -- sectors ---------------------------------------------------------
    def _sector(self, index: int) -> bytes:
        start = 512 + index * self.sector_size
        return self.data[start:start + self.sector_size]

    def _read_fat(self) -> list:
        difat = [_u32(self.data, 76 + 4 * i) for i in range(109)]
        nxt = self.difat_start
        guard = 0
        while nxt not in (ENDOFCHAIN, FREESECT) and guard < 1024:
            sector = self._sector(nxt)
            count = self.sector_size // 4 - 1
            difat.extend(_u32(sector, 4 * i) for i in range(count))
            nxt = _u32(sector, self.sector_size - 4)
            guard += 1

        fat = []
        for sec in difat:
            if sec in (ENDOFCHAIN, FREESECT) or sec >= len(self.data) // max(1, self.sector_size) + 1:
                continue
            chunk = self._sector(sec)
            if len(chunk) < self.sector_size:
                chunk = chunk.ljust(self.sector_size, b"\x00")
            fat.extend(_u32(chunk, 4 * i) for i in range(self.sector_size // 4))
        return fat

    def _read_minifat(self) -> list:
        if self.minifat_start in (ENDOFCHAIN, FREESECT) or not self.num_minifat:
            return []
        raw = self._read_chain(self.minifat_start, None, mini=False)
        count = len(raw) // 4
        return [_u32(raw, 4 * i) for i in range(count)]

    def _read_chain(self, start: int, size, mini: bool) -> bytes:
        out = bytearray()
        sector = start
        guard = 0
        table = self.minifat if mini else self.fat
        unit = self.mini_size if mini else self.sector_size
        while sector not in (ENDOFCHAIN, FREESECT) and guard < 100000:
            if mini:
                offset = sector * unit
                chunk = self.mini_stream[offset:offset + unit]
            else:
                chunk = self._sector(sector)
            if not chunk:
                break
            out.extend(chunk)
            if sector >= len(table):
                break
            sector = table[sector]
            guard += 1
            if size is not None and len(out) >= size:
                break
        return bytes(out[:size]) if size is not None else bytes(out)

    # -- directory -------------------------------------------------------
    def _read_directory(self) -> list:
        raw = self._read_chain(self.dir_start, None, mini=False)
        entries = []
        for off in range(0, len(raw) - 127, 128):
            name_len = _u16(raw, off + 64)
            if name_len < 2 or name_len > 64:
                continue
            name = raw[off:off + name_len - 2].decode("utf-16-le", "replace")
            entries.append({
                "name": name,
                "type": raw[off + 66],
                "start": _u32(raw, off + 116),
                "size": _u32(raw, off + 120),
            })
        return entries

    def stream(self, name: str):
        for entry in self.entries:
            if entry["name"] == name and entry["type"] == 2:
                size = entry["size"]
                if size >= self.mini_cutoff:
                    return self._read_chain(entry["start"], size, mini=False)
                return self._read_chain(entry["start"], size, mini=True)
        return None


class PptDocument:
    def __init__(self, data: bytes):
        self.cfb = CompoundFile(data)
        stream = self.cfb.stream("PowerPoint Document")
        if stream is None:
            raise PptError("这个 .ppt 里没有幻灯片内容（可能是其它 Office 文件改名）")
        self.stream = stream

    # -- record walking --------------------------------------------------
    def _children(self, start: int, end: int):
        """逐个产出 (type, instance, body_start, body_len)。"""
        i = start
        while i + 8 <= end:
            ver_inst = _u16(self.stream, i)
            rec_type = _u16(self.stream, i + 2)
            rec_len = _u32(self.stream, i + 4)
            body = i + 8
            if rec_len < 0 or body + rec_len > end:
                break
            yield ver_inst & 0x000F, ver_inst >> 4, rec_type, body, rec_len
            i = body + rec_len

    def _walk(self, start, end, depth=0):
        """深度优先遍历，产出 (type, instance, body_start, body_len)。"""
        if depth > 24:
            return
        for ver, inst, rec_type, body, length in self._children(start, end):
            yield rec_type, inst, body, length
            if ver == 0xF or rec_type in (RT_DOCUMENT, RT_SLIDE, RT_SLIDE_LIST_WITH_TEXT):
                for item in self._walk(body, body + length, depth + 1):
                    yield item

    def _decode(self, kind: int, body: int, length: int) -> str:
        raw = self.stream[body:body + length]
        if kind == RT_TEXT_CHARS:
            return raw.decode("utf-16-le", "replace")
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "replace")

    # -- public ----------------------------------------------------------
    def slide_texts(self) -> list:
        """按放映顺序返回每页文字；失败时退回文件顺序。"""
        slides = self._from_slide_list()
        if not slides:
            slides = self._from_slide_containers()
        return slides

    def _from_slide_list(self) -> list:
        """SlideListWithText 里的顺序就是放映顺序。"""
        for rec_type, inst, body, length in self._walk(0, len(self.stream)):
            if rec_type != RT_SLIDE_LIST_WITH_TEXT or inst != 0:
                continue
            slides, current = [], None
            for _v, _i, kind, b, ln in self._children(body, body + length):
                if kind == RT_SLIDE_PERSIST:
                    current = []
                    slides.append(current)
                elif kind in (RT_TEXT_CHARS, RT_TEXT_BYTES) and current is not None:
                    current.append(self._decode(kind, b, ln))
            if slides:
                return [" ".join(parts) for parts in slides]
        return []

    def _from_slide_containers(self) -> list:
        slides = []
        current = None
        for rec_type, _inst, body, length in self._walk(0, len(self.stream)):
            if rec_type == RT_SLIDE:
                current = []
                slides.append(current)
            elif rec_type in (RT_TEXT_CHARS, RT_TEXT_BYTES) and current is not None:
                current.append(self._decode(rec_type, body, length))
        return [" ".join(parts) for parts in slides]


_CTRL = {0x0B: " ", 0x0D: " ", 0x0A: " ", 0x09: " "}


def _clean(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if ch in _CTRL:
            out.append(_CTRL[ch])
        elif code < 0x20 or code == 0x7F:
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def extract_pages(data: bytes) -> list:
    """返回 [{"n": 1, "text": "..."}, ...]，和 pptxtext 的输出结构一致。"""
    doc = PptDocument(data)
    raw_slides = doc.slide_texts()
    pages = []
    for index, text in enumerate(raw_slides, 1):
        pages.append({"n": index, "text": _clean(text)})
    if not pages:
        raise PptError("没能从这份 .ppt 里读到文字（扫描版或纯图片幻灯片）")
    return pages


def looks_like_ppt(data: bytes) -> bool:
    return len(data) > 512 and data[:8] == CFB_MAGIC
