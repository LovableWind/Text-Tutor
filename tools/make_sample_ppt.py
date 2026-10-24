# -*- coding: utf-8 -*-
"""生成一份最小可用的 .ppt（OLE 复合文档 + PowerPoint 文本记录），用于测试与示例。

真实的 .ppt 由 PowerPoint 写出，结构更复杂；这里只实现解析器用到的那一小部分，
足以验证 CFB 读取、记录遍历和按幻灯片切分。
"""

from __future__ import annotations

import os
import struct

SECTOR = 512
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD

RT_DOCUMENT = 0x03E8
RT_SLIDE_LIST_WITH_TEXT = 0x0FF0
RT_TEXT_CHARS = 0x0FA0
RT_TEXT_HEADER = 0x0F9E
RT_SLIDE_PERSIST = 0x03F3


def rec(rec_type: int, body: bytes, container: bool = False) -> bytes:
    ver_inst = 0x000F if container else 0x0000
    return struct.pack("<HHI", ver_inst, rec_type, len(body)) + body


def text_atom(text: str) -> bytes:
    return rec(RT_TEXT_CHARS, text.encode("utf-16-le"))


def slide_list(slides: list) -> bytes:
    body = b""
    for index, text in enumerate(slides, 1):
        body += rec(RT_SLIDE_PERSIST, struct.pack("<IIIII", index, 0, 0, 0, 0))
        body += rec(RT_TEXT_HEADER, struct.pack("<I", 0))
        body += text_atom(text)
    return rec(RT_DOCUMENT, rec(RT_SLIDE_LIST_WITH_TEXT, body, container=True), container=True)


def directory_entry(name: str, obj_type: int, start: int, size: int) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00"
    entry = bytearray(128)
    entry[0:len(raw)] = raw
    struct.pack_into("<H", entry, 64, len(raw))
    entry[66] = obj_type
    entry[67] = 1
    struct.pack_into("<III", entry, 68, FREESECT, FREESECT, FREESECT)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<I", entry, 120, size)
    return bytes(entry)


def build(slides: list) -> bytes:
    stream = slide_list(slides)
    if len(stream) < 4096:
        stream += b"\x00" * (4096 - len(stream))
    data_sectors = (len(stream) + SECTOR - 1) // SECTOR
    first_data = 2
    total_sectors = 2 + data_sectors

    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 24, 0x003E)   # minor
    struct.pack_into("<H", header, 26, 3)        # major
    struct.pack_into("<H", header, 28, 0xFFFE)   # byte order
    struct.pack_into("<H", header, 30, 9)        # sector shift
    struct.pack_into("<H", header, 32, 6)        # mini sector shift
    struct.pack_into("<I", header, 44, 1)        # FAT 扇区数
    struct.pack_into("<I", header, 48, 1)        # 目录起始扇区
    struct.pack_into("<I", header, 56, 4096)     # mini cutoff
    struct.pack_into("<I", header, 60, ENDOFCHAIN)
    struct.pack_into("<I", header, 64, 0)
    struct.pack_into("<I", header, 68, ENDOFCHAIN)
    struct.pack_into("<I", header, 72, 0)
    struct.pack_into("<I", header, 76, 0)        # DIFAT[0] = FAT 在扇区 0
    for i in range(1, 109):
        struct.pack_into("<I", header, 76 + 4 * i, FREESECT)

    fat = [FATSECT, ENDOFCHAIN]
    for i in range(data_sectors):
        sector = first_data + i
        fat.append(sector + 1 if i < data_sectors - 1 else ENDOFCHAIN)
    while len(fat) < SECTOR // 4:
        fat.append(FREESECT)
    fat_sector = struct.pack("<%dI" % (SECTOR // 4), *fat)

    entries = directory_entry("Root Entry", 5, ENDOFCHAIN, 0)
    entries += directory_entry("PowerPoint Document", 2, first_data, len(stream))
    entries = entries.ljust(SECTOR, b"\x00")

    out = bytes(header) + fat_sector + entries + stream
    pad = total_sectors * SECTOR + 512 - len(out)
    if pad > 0:
        out += b"\x00" * pad
    return out


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "samples", "课件示例", "第3讲 导数的应用.ppt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    slides = [
        "第三章 导数的应用 3.1 洛必达法则 定理 3.1 若 lim f(x) = lim g(x) = 0，且 g'(x) 不为零",
        "3.2 函数的单调性 定理 3.2 若 f'(x) > 0，则 f 在此区间单调递增",
        "3.3 极值与最值 定义 3.2 若在 x0 的去心邻域内 f(x) < f(x0)，则 x0 是极大值点",
        "习题 3.1 求 f(x) = x^3 - 3x 的单调区间与极值",
    ]
    data = build(slides)
    with open(out, "wb") as fh:
        fh.write(data)
    print("wrote %s (%d bytes, %d slides)" % (out, len(data), len(slides)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
