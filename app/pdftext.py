# -*- coding: utf-8 -*-
"""Pure-Python PDF text extraction.

Enough PDF for lecture handouts: classic xref files, cross-reference streams,
object streams, Flate compression, Type0/TrueType/Type1/Type3 fonts with
ToUnicode CMaps, simple encodings with /Differences, and the usual text
operators.  No third-party dependencies.

Public API:
    doc = PdfDocument.from_bytes(data)
    doc.page_count
    doc.page_text(index)          # 0-based, str
    doc.pages_text()              # list[str]
"""

from __future__ import annotations

import re
import zlib

WS = b" \t\r\n\f\x00"
DELIMS = b"()<>[]{}/%"

# --------------------------------------------------------------------------
# low-level object reader
# --------------------------------------------------------------------------


class Name(str):
    """A PDF name (stored without the leading slash)."""


class Ref(tuple):
    """An indirect reference (num, gen)."""

    @property
    def num(self):
        return self[0]


class Stream:
    __slots__ = ("dict", "raw")

    def __init__(self, d, raw):
        self.dict = d
        self.raw = raw

    def __repr__(self):
        return "<Stream %r bytes=%d>" % (self.dict.get("Type"), len(self.raw))


def _skip_ws(buf, i):
    n = len(buf)
    while i < n and buf[i] in WS:
        i += 1
    return i


def parse_obj(buf, i):
    """Parse one PDF object starting at i.  Returns (obj, next_index)."""
    n = len(buf)
    i = _skip_ws(buf, i)
    if i >= n:
        return None, i
    c = buf[i : i + 1]
    if c == b"/":
        j = i + 1
        while j < n and buf[j] not in WS and buf[j] not in DELIMS:
            j += 1
        raw = buf[i + 1 : j]
        # #xx escapes in names
        if b"#" in raw:
            raw = re.sub(
                rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw
            )
        return Name(raw.decode("latin-1")), j
    if c == b"(":
        return _parse_literal(buf, i)
    if buf[i : i + 2] == b"<<":
        return _parse_dict(buf, i)
    if c == b"<":
        j = buf.find(b">", i)
        if j == -1:
            return b"", n
        hx = re.sub(rb"[^0-9A-Fa-f]", b"", buf[i + 1 : j])
        if len(hx) % 2:
            hx += b"0"
        return bytes.fromhex(hx.decode()), j + 1
    if c == b"[":
        i += 1
        arr = []
        while True:
            i = _skip_ws(buf, i)
            if i >= n:
                return arr, i
            if buf[i : i + 1] == b"]":
                return arr, i + 1
            obj, i = parse_obj(buf, i)
            arr.append(obj)
    # keyword or number
    j = i
    while j < n and buf[j] not in WS and buf[j] not in DELIMS:
        j += 1
    if j == i:
        return None, i + 1
    word = buf[i:j]
    if re.fullmatch(rb"[+-]?\d+", word):
        val = int(word)
        # lookahead "G R"
        k = _skip_ws(buf, j)
        m = re.match(rb"(\d+)\s+R\b", buf[k : k + 24])
        if m:
            return Ref((val, int(m.group(1)))), k + m.end()
        return val, j
    if re.fullmatch(rb"[+-]?(\d+\.\d*|\.\d+)", word):
        try:
            return float(word), j
        except ValueError:
            return 0.0, j
    return word, j


def _parse_literal(buf, i):
    # i points at '('
    n = len(buf)
    i += 1
    depth = 1
    out = bytearray()
    while i < n:
        ch = buf[i]
        if ch == 0x5C:  # backslash
            nxt = buf[i + 1 : i + 2]
            mp = {
                b"n": b"\n",
                b"r": b"\r",
                b"t": b"\t",
                b"b": b"\b",
                b"f": b"\f",
                b"(": b"(",
                b")": b")",
                b"\\": b"\\",
            }
            if nxt in mp:
                out += mp[nxt]
                i += 2
            elif nxt.isdigit():
                j = i + 1
                oct_ = b""
                while j < n and buf[j : j + 1].isdigit() and len(oct_) < 3:
                    oct_ += buf[j : j + 1]
                    j += 1
                out.append(int(oct_, 8) & 0xFF)
                i = j
            elif nxt in (b"\n", b"\r"):
                i += 2
            else:
                out += nxt
                i += 2
            continue
        if ch == 0x28:
            depth += 1
            out.append(ch)
        elif ch == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return bytes(out), n


def _parse_dict(buf, i):
    # i points at '<<'
    n = len(buf)
    i += 2
    d = {}
    while True:
        i = _skip_ws(buf, i)
        if i >= n:
            return d, i
        if buf[i : i + 2] == b">>":
            return d, i + 2
        key, i = parse_obj(buf, i)
        if not isinstance(key, Name):
            continue
        i = _skip_ws(buf, i)
        if buf[i : i + 2] == b">>":
            d[str(key)] = None
            return d, i + 2
        val, i = parse_obj(buf, i)
        d[str(key)] = val


class PdfDocument:
    def __init__(self, data: bytes):
        self.data = data
        self.objs = {}          # num -> (dict_part_bytes, stream_bytes|None)
        self._cache = {}
        self._scan_objects()
        self._expand_object_streams()
        self.pages = self._collect_pages()

    # -- construction -----------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(data)

    @classmethod
    def from_path(cls, path):
        with open(path, "rb") as fh:
            return cls(fh.read())

    def _scan_objects(self):
        data = self.data
        pat = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
        pos = 0
        while True:
            m = pat.search(data, pos)
            if not m:
                break
            num = int(m.group(1))
            i = m.end()
            sidx = data.find(b"stream", i)
            eidx = data.find(b"endobj", i)
            if sidx != -1 and (eidx == -1 or sidx < eidx):
                body = data[i:sidx]
                s = sidx + 6
                if data[s : s + 2] == b"\r\n":
                    s += 2
                elif data[s : s + 1] in (b"\n", b"\r"):
                    s += 1
                lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", body)
                if lm:
                    ln = int(lm.group(1))
                    raw = data[s : s + ln]
                    endstream = data.find(b"endstream", s + ln)
                else:
                    endstream = data.find(b"endstream", s)
                    if endstream == -1:
                        endstream = data.find(b"endobj", s)
                    raw = data[s:endstream] if endstream != -1 else data[s:]
                    raw = raw.rstrip(b"\r\n")
                nxt = data.find(b"endobj", endstream if endstream != -1 else s)
                pos = nxt + 6 if nxt != -1 else len(data)
            else:
                body = data[i : eidx if eidx != -1 else len(data)]
                raw = None
                pos = (eidx + 6) if eidx != -1 else len(data)
            self.objs[num] = (body, raw)   # later definitions win (incremental updates)

    def _expand_object_streams(self):
        extra = {}
        for num, (body, raw) in list(self.objs.items()):
            if raw is None or b"/ObjStm" not in body:
                continue
            try:
                d, _ = parse_obj(body, 0)
                if not isinstance(d, dict):
                    continue
                data = self.decode_stream(Stream(d, raw))
                first = int(self.resolve(d.get("First", 0)))
                count = int(self.resolve(d.get("N", 0)))
                header = data[:first].split()
                pairs = [(int(header[k]), int(header[k + 1])) for k in range(0, min(len(header), 2 * count), 2)]
                for idx, (onum, off) in enumerate(pairs):
                    start = first + off
                    end = first + pairs[idx + 1][1] if idx + 1 < len(pairs) else len(data)
                    extra[onum] = (data[start:end], None)
            except Exception:
                continue
        for onum, val in extra.items():
            self.objs.setdefault(onum, val)

    # -- object access ----------------------------------------------------
    def body(self, num):
        return self.objs.get(num, (b"", None))[0]

    def resolve(self, obj, depth=0):
        while isinstance(obj, Ref) and depth < 32:
            obj = self.get(obj.num)
            depth += 1
        return obj

    def get(self, num):
        if num in self._cache:
            return self._cache[num]
        body, raw = self.objs.get(num, (b"", None))
        try:
            obj, _ = parse_obj(body, 0)
        except Exception:
            obj = None
        if raw is not None:
            stream_start = body.find(b"stream")
            d = obj if isinstance(obj, dict) else {}
            obj = Stream(d, raw)
        self._cache[num] = obj
        return obj

    def dict_of(self, obj):
        obj = self.resolve(obj)
        if isinstance(obj, Stream):
            return obj.dict
        if isinstance(obj, dict):
            return obj
        return {}

    def decode_stream(self, stream: Stream) -> bytes:
        d = stream.dict
        filt = self.resolve(d.get("Filter"))
        if filt is None:
            return stream.raw
        filters = filt if isinstance(filt, list) else [filt]
        data = stream.raw
        for f in filters:
            f = str(self.resolve(f))
            if f in ("FlateDecode", "Fl"):
                data = _inflate(data)
            elif f in ("ASCIIHexDecode", "AHx"):
                hx = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
                if len(hx) % 2:
                    hx += b"0"
                data = bytes.fromhex(hx.decode())
            elif f in ("ASCII85Decode", "A85"):
                data = _a85(data)
            else:
                # unsupported filter (DCT/JPX/CCITT...): return raw, caller decides
                return data
        return data

    def stream_data(self, obj) -> bytes:
        obj = self.resolve(obj)
        if isinstance(obj, Stream):
            return self.decode_stream(obj)
        return b""

    # -- page tree ---------------------------------------------------------
    def _collect_pages(self):
        roots = []
        all_pages = []
        for num, (body, raw) in self.objs.items():
            if raw is None and re.search(rb"/Type\s*/Page\b", body):
                # avoid /Pages matching /Page\b (it won't)
                all_pages.append(num)
            if raw is None and re.search(rb"/Type\s*/Catalog\b", body):
                roots.append(num)
        order = []
        if roots:
            for r in sorted(roots):
                cat = self.dict_of(r)
                node = cat.get("Pages")
                self._walk_pages(node, order, set(), 0)
        if order:
            # keep only real pages
            order = [n for n in order if n in self.objs]
            if order:
                return order
        return sorted(set(all_pages))

    def _walk_pages(self, node, out, seen, depth):
        if depth > 64:
            return
        ref = node.num if isinstance(node, Ref) else None
        if ref is not None:
            if ref in seen:
                return
            seen.add(ref)
        d = self.dict_of(node)
        kids = self.resolve(d.get("Kids"))
        typ = str(self.resolve(d.get("Type")) or "")
        if typ == "Page" or (kids is None and typ != "Pages"):
            if ref is not None:
                out.append(ref)
            return
        if isinstance(kids, list):
            for kid in kids:
                self._walk_pages(kid, out, seen, depth + 1)

    @property
    def page_count(self):
        return len(self.pages)

    # -- text --------------------------------------------------------------
    def page_text(self, index: int) -> str:
        if index < 0 or index >= len(self.pages):
            return ""
        num = self.pages[index]
        page = self.get(num)
        pdict = self.dict_of(page)
        resources = self._resource_dict(pdict, 0)
        fonts = self._page_fonts(resources)
        contents = self.resolve(pdict.get("Contents"))
        chunks = []
        if isinstance(contents, list):
            for c in contents:
                chunks.append(self.stream_data(c))
        else:
            chunks.append(self.stream_data(contents))
        buf = b"\n".join(chunks)
        text = _ContentInterpreter(self, fonts).run(buf)
        return text

    def pages_text(self):
        return [self.page_text(i) for i in range(len(self.pages))]

    def _resource_dict(self, pdict, depth):
        res = self.resolve(pdict.get("Resources"))
        if isinstance(res, dict):
            return res
        parent = pdict.get("Parent")
        if parent is not None and depth < 16:
            pd = self.dict_of(parent)
            return self._resource_dict(pd, depth + 1)
        return {}

    def _page_fonts(self, resources):
        out = {}
        fonts = self.resolve(resources.get("Font")) if resources else None
        if isinstance(fonts, dict):
            for name, ref in fonts.items():
                out[name] = self.resolve(ref)
        return out

    def font_decoder(self, font):
        key = id(font)
        cache = self.__dict__.setdefault("_font_cache", {})
        if key in cache:
            return cache[key]
        dec = _FontDecoder(self, font)
        cache[key] = dec
        return dec


def _inflate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except Exception:
        pass
    try:
        return zlib.decompressobj().decompress(data)
    except Exception:
        pass
    # tolerate leading whitespace / trailing junk
    for skip in range(1, 4):
        try:
            return zlib.decompressobj().decompress(data[skip:])
        except Exception:
            continue
    return b""


def _a85(data: bytes) -> bytes:
    data = re.sub(rb"\s", b"", data)
    if data.startswith(b"<~"):
        data = data[2:]
    data = data.split(b"~>")[0]
    out = bytearray()
    group = []
    for ch in data:
        if ch == 0x7A and not group:  # 'z'
            out += b"\0\0\0\0"
            continue
        group.append(ch - 33)
        if len(group) == 5:
            val = 0
            for g in group:
                val = val * 85 + g
            out += val.to_bytes(4, "big")
            group = []
    if group:
        pad = 5 - len(group)
        val = 0
        for g in group + [84] * pad:
            val = val * 85 + g
        out += val.to_bytes(4, "big")[: 4 - pad]
    return bytes(out)


# --------------------------------------------------------------------------
# fonts / CMaps
# --------------------------------------------------------------------------


class _FontDecoder:
    def __init__(self, doc: PdfDocument, font):
        self.doc = doc
        d = doc.dict_of(font)
        self.d = d
        self.subtype = str(doc.resolve(d.get("Subtype")) or "")
        self.cmap = {}
        self.code_lens = [1]
        self.vertical = False
        self.base = {}
        tu = d.get("ToUnicode")
        if tu is not None:
            try:
                self.cmap = _parse_cmap(doc.stream_data(tu))
            except Exception:
                self.cmap = {}
        if self.cmap:
            self.code_lens = sorted({k[0] for k in self.cmap})
        enc = doc.resolve(d.get("Encoding"))
        if isinstance(enc, dict):
            self.base = _differences(doc.resolve(enc.get("Differences")))
        elif isinstance(enc, str):
            self.base = {}
        if self.subtype == "Type0":
            self.vertical = True

    def decode(self, s: bytes) -> str:
        out = []
        i = 0
        n = len(s)
        lens = sorted(self.code_lens, reverse=True) or [1]
        while i < n:
            done = False
            for ln in lens:
                if i + ln > n:
                    continue
                code = int.from_bytes(s[i : i + ln], "big")
                if (ln, code) in self.cmap:
                    out.append(self.cmap[(ln, code)])
                    i += ln
                    done = True
                    break
            if done:
                continue
            # simple font fallback
            b = s[i]
            if b in self.base:
                out.append(self.base[b])
            else:
                out.append(bytes([b]).decode("latin-1"))
            i += 1
        return "".join(out)


def _differences(arr) -> dict:
    out = {}
    if not isinstance(arr, list):
        return out
    code = 0
    for item in arr:
        if isinstance(item, int):
            code = item
        elif isinstance(item, Name):
            out[code] = _glyph_to_char(str(item))
            code += 1
    return out


_GLYPHS = {
    "space": " ",
    "period": ".",
    "comma": ",",
    "colon": ":",
    "semicolon": ";",
    "quotesingle": "'",
    "quotedbl": '"',
    "hyphen": "-",
    "endash": "–",
    "emdash": "—",
    "parenleft": "(",
    "parenright": ")",
    "bracketleft": "[",
    "bracketright": "]",
    "braceleft": "{",
    "braceright": "}",
    "slash": "/",
    "backslash": "\\",
    "equal": "=",
    "plus": "+",
    "minus": "-",
    "asterisk": "*",
    "less": "<",
    "greater": ">",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "sigma": "σ",
    "phi": "φ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω",
    "infinity": "∞", "summation": "∑", "integral": "∫", "radical": "√",
    "arrowright": "→", "lessequal": "≤", "greaterequal": "≥", "notequal": "≠",
    "approxequal": "≈", "element": "∈", "universal": "∀", "existential": "∃",
    "partialdiff": "∂", "nabla": "∇", "angle": "∠", "perpendicular": "⊥",
}

_UNI_RE = re.compile(r"(?:uni([0-9A-Fa-f]{4,6}))|(?:u([0-9A-Fa-f]{4,6}))")


def _glyph_to_char(name: str) -> str:
    if name in _GLYPHS:
        return _GLYPHS[name]
    m = _UNI_RE.fullmatch(name)
    if m:
        cp = int(m.group(1) or m.group(2), 16)
        if cp < 0x110000:
            return chr(cp)
    if len(name) == 1:
        return name
    return ""


def _hex_to_unicode(dst: str) -> str:
    if not dst:
        return ""
    if len(dst) % 4 == 0:
        try:
            return bytes.fromhex(dst).decode("utf-16-be", "replace")
        except Exception:
            pass
    try:
        return bytes.fromhex(dst).decode("utf-16-be", "replace")
    except Exception:
        return ""


def _parse_cmap(data: bytes) -> dict:
    cmap = {}
    if not data:
        return cmap
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
            s = src.decode()
            d = dst.decode()
            cmap[(len(s) // 2, int(s, 16))] = _hex_to_unicode(d)
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        pat3 = re.compile(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(?:<([0-9A-Fa-f]*)>|\[(.*?)\])",
            re.S,
        )
        for m in pat3.finditer(blk):
            lo, hi = m.group(1).decode(), m.group(2).decode()
            a, b = int(lo, 16), int(hi, 16)
            ln = len(lo) // 2
            if m.group(3) is not None:
                base = m.group(3).decode()
                start = _hex_to_unicode(base)
                if not start:
                    continue
                base_cp = ord(start[0])
                prefix, suffix = start[1:], ""
                if len(start) > 1:
                    prefix, suffix = start[:-1], start[-1]
                for k in range(a, min(b, a + 65535) + 1):
                    off = k - a
                    cp = base_cp + off
                    try:
                        ch = chr(cp)
                    except ValueError:
                        continue
                    cmap[(ln, k)] = prefix + ch + suffix if off and suffix else ch
            else:
                items = re.findall(rb"<([0-9A-Fa-f]*)>", m.group(4) or b"")
                for i, it in enumerate(items):
                    cmap[(ln, a + i)] = _hex_to_unicode(it.decode())
    return cmap


# --------------------------------------------------------------------------
# content stream interpreter
# --------------------------------------------------------------------------


def _tokenize(buf: bytes):
    i = 0
    n = len(buf)
    while i < n:
        c = buf[i : i + 1]
        if c in (b" ", b"\t", b"\r", b"\n", b"\f", b"\x00"):
            i += 1
            continue
        if c == b"%":
            while i < n and buf[i : i + 1] not in (b"\r", b"\n"):
                i += 1
            continue
        if c in (b"(", b"<", b"[", b"/") or c.isdigit() or c in (b"-", b"+", b"."):
            obj, i = parse_obj(buf, i)
            yield ("val", obj)
            continue
        if c == b"]":
            yield ("op", b"]")
            i += 1
            continue
        if c == b">":
            i += 2
            continue
        j = i
        while j < n and buf[j : j + 1] not in WS and buf[j : j + 1] not in DELIMS:
            j += 1
        if j == i:
            i += 1
            continue
        yield ("op", buf[i:j])
        i = j


class _ContentInterpreter:
    """Runs a page content stream and rebuilds readable text lines."""

    def __init__(self, doc, fonts):
        self.doc = doc
        self.fonts = fonts
        self.decoders = {}
        self.out = []
        self.line = []
        self.cur_font = None
        self.line_y = None
        self.last_x = None
        self.prev_end_x = None
        self.in_text = False

    def _decoder(self, name):
        if name not in self.decoders:
            font = self.fonts.get(name)
            self.decoders[name] = self.doc.font_decoder(font) if font is not None else None
        return self.decoders[name]

    def _flush_line(self):
        if self.line:
            text = "".join(self.line)
            text = re.sub(r"[ \t]+", " ", text).strip()
            if text:
                self.out.append(text)
        self.line = []
        self.prev_end_x = None

    def _feed(self, s: str, x=None):
        if not s:
            return
        if x is not None and self.prev_end_x is not None and self.line:
            gap = x - self.prev_end_x
            if gap > 6 and not self.line[-1].endswith(" ") and not s.startswith(" "):
                self.line.append(" ")
        self.line.append(s)
        self.prev_end_x = None if x is None else x

    def run(self, buf):
        stack = []
        tm = [1, 0, 0, 1, 0, 0]
        tlm = [1, 0, 0, 1, 0, 0]
        leading = 0.0
        for kind, val in _tokenize(buf):
            if kind == "val":
                stack.append(val)
                continue
            op = val
            if op == b"BT":
                self.in_text = True
                tm = [1, 0, 0, 1, 0, 0]
                tlm = list(tm)
                stack = []
            elif op == b"ET":
                self.in_text = False
                self._flush_line()
                stack = []
            elif op == b"Tf":
                names = [v for v in stack if isinstance(v, Name)]
                if names:
                    self.cur_font = str(names[-1])
                stack = []
            elif op in (b"Td", b"TD"):
                nums = [v for v in stack if isinstance(v, (int, float))]
                if len(nums) >= 2:
                    tx, ty = nums[-2], nums[-1]
                    tlm[4] += tx * tlm[0] + ty * tlm[2]
                    tlm[5] += tx * tlm[1] + ty * tlm[3]
                    tm = list(tlm)
                    if op == b"TD":
                        leading = -ty
                    if abs(ty) > 0.5:
                        self._flush_line()
                stack = []
            elif op == b"Tm":
                nums = [v for v in stack if isinstance(v, (int, float))]
                if len(nums) >= 6:
                    tlm = list(nums[-6:])
                    tm = list(tlm)
                    if self.line_y is not None and abs(tm[5] - self.line_y) > 0.5:
                        self._flush_line()
                    self.line_y = tm[5]
                stack = []
            elif op == b"T*":
                tlm[4] += -leading * tlm[2]
                tlm[5] += -leading * tlm[3]
                tm = list(tlm)
                self._flush_line()
                stack = []
            elif op in (b"Tj", b"'", b'"'):
                if op in (b"'", b'"'):
                    self._flush_line()
                dec = self._decoder(self.cur_font)
                for item in stack:
                    if isinstance(item, bytes):
                        self._flush_line()
                        self._feed(dec.decode(item) if dec else item.decode("latin-1"), tm[4])
                stack = []
            elif op == b"TJ":
                dec = self._decoder(self.cur_font)
                arr = next((v for v in reversed(stack) if isinstance(v, list)), None)
                if arr is not None:
                    for item in arr:
                        if isinstance(item, bytes):
                            self._feed(dec.decode(item) if dec else item.decode("latin-1"), tm[4])
                        elif isinstance(item, (int, float)) and item < -120:
                            if self.line and not self.line[-1].endswith(" "):
                                self.line.append(" ")
                stack = []
            elif op in (b"cm", b"q", b"Q", b"gs", b"re", b"W", b"n", b"cs", b"sc", b"rg",
                        b"RG", b"g", b"G", b"k", b"K", b"scn", b"SCN", b"f", b"S", b"B",
                        b"d0", b"d1", b"BDC", b"EMC", b"BMC", b"sh", b"Do", b"BI", b"ID",
                        b"EI", b"Tc", b"Tw", b"Tz", b"TL", b"Ts", b"Tr", b"w", b"J", b"j",
                        b"M", b"d", b"ri", b"i", b"m", b"l", b"c", b"v", b"y", b"h", b"f*",
                        b"B*", b"b", b"b*", b"S*", b"n", b"W*"):
                stack = []
            else:
                stack = []
        self._flush_line()
        return "\n".join(self.out).strip()
