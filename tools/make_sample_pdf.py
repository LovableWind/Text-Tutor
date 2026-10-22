# -*- coding: utf-8 -*-
"""Generate a small Chinese maths handout PDF for tests and for the demo.

The glyphs are Type3 procedures that draw nothing, but every glyph carries a real
Unicode mapping, so the file behaves like a text-layer PDF for extraction
purposes while staying a few kilobytes.
"""

from __future__ import annotations

import os
import sys

CONTENT_LINALG = [
    [
        "第一章 矩阵与行列式",
        "1.1 矩阵的乘法",
        "定义 1.1 设 A=(a_ij) 是 m×n 矩阵，B=(b_ij) 是 n×p 矩阵，",
        "则 AB 是 m×p 矩阵，其第 i 行第 j 列元素为 sum a_ik b_kj。",
        "例 1.1 设 A=[[1,2],[3,4]]，B=[[0,1],[1,0]]，求 AB。",
        "性质 (AB)C = A(BC)，但一般 AB ≠ BA。",
        "1.2 行列式",
        "定义 1.2 二阶行列式 |a b; c d| = ad - bc。",
    ],
    [
        "定理 1.1 行列式的性质：det(AB) = det A · det B。",
        "推论 若 A 可逆，则 det(A^-1) = 1/det A。",
        "例 1.2 计算 det([[1,2],[3,4]]) = 1×4 - 2×3 = -2。",
        "1.3 逆矩阵",
        "定义 1.3 若 AB = BA = I，则称 B 是 A 的逆矩阵，记作 A^-1。",
        "定理 1.2 A 可逆当且仅当 det A ≠ 0。",
    ],
    [
        "第二章 向量空间",
        "2.1 线性相关性",
        "定义 2.1 若存在不全为零的数 k_1,…,k_s 使 k_1 a_1 + … + k_s a_s = 0，",
        "则称向量组 a_1,…,a_s 线性相关；否则称线性无关。",
        "例 2.1 判断 (1,0),(0,1),(1,1) 是否线性相关。",
        "2.2 秩",
        "定义 2.2 向量组的极大线性无关组所含向量个数称为秩。",
    ],
    [
        "2.3 特征值与特征向量",
        "定义 2.3 若存在非零向量 x 使 Ax = λx，则称 λ 是 A 的特征值，x 是对应特征向量。",
        "定理 2.1 λ 是 A 的特征值当且仅当 det(λI - A) = 0。",
        "2.4 对角化",
        "定理 2.2 n 阶矩阵 A 可对角化当且仅当它有 n 个线性无关的特征向量。",
        "习题 2.1 求 A=[[2,1],[1,2]] 的特征值与特征向量。",
    ],
]

CONTENT = [
    # (page, [lines])
    [
        "第一章 极限与连续",
        "1.1 数列的极限",
        "定义 1.1 设 {a_n} 是一个数列，A 是一个常数。若对任意 ε>0，存在正整数 N，",
        "使得当 n>N 时恒有 |a_n - A| < ε，则称数列 {a_n} 收敛于 A，记作 lim a_n = A。",
        "例 1.1 用定义证明 lim (n+1)/n = 1。",
        "证明 对任意 ε>0，取 N = [1/ε]+1，当 n>N 时，|(n+1)/n - 1| = 1/n < ε。",
        "1.2 收敛数列的性质",
        "定理 1.1（唯一性）收敛数列的极限唯一。",
        "定理 1.2（有界性）收敛数列必有界。",
        "定理 1.3（保号性）若 lim a_n = A > 0，则存在 N，当 n>N 时 a_n > 0。",
    ],
    [
        "1.3 单调有界准则",
        "定理 1.4 单调有界数列必有极限。",
        "证明思路 以单调递增且有上界为例，取上确界 A，验证 A 就是极限。",
        "例 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。",
        "解 先用归纳法证明 a_n < 2，再证明 a_{n+1} - a_n > 0，故单调递增有上界。",
        "设极限为 A，则 A = sqrt(2 + A)，解得 A = 2。",
        "1.4 两个重要极限",
        "公式 lim (sin x)/x = 1 (x→0)，lim (1+1/n)^n = e。",
    ],
    [
        "第二章 导数与微分",
        "2.1 导数的定义",
        "定义 2.1 设函数 y=f(x) 在点 x_0 的某邻域内有定义，若极限",
        "lim [f(x_0+Δx) - f(x_0)]/Δx (Δx→0) 存在，则称 f 在 x_0 处可导。",
        "定理 2.1 可导必连续，连续不一定可导。",
        "例 2.1 求 f(x)=x^2 在 x=1 处的导数。",
        "2.2 求导法则",
        "公式 (uv)' = u'v + uv'，(u/v)' = (u'v - uv')/v^2。",
    ],
    [
        "2.3 高阶导数与微分",
        "定义 2.2 二阶导数记作 f''(x) 或 d^2y/dx^2。",
        "定理 2.2（莱布尼茨公式）(uv)^(n) = sum C(n,k) u^(k) v^(n-k)。",
        "2.4 微分中值定理",
        "定理 2.3（罗尔定理）若 f 在 [a,b] 连续，在 (a,b) 可导，且 f(a)=f(b)，",
        "则存在 ξ∈(a,b)，使 f'(ξ)=0。",
        "定理 2.4（拉格朗日中值定理）f(b)-f(a) = f'(ξ)(b-a)。",
        "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
    ],
]

SETS = {"calculus": CONTENT, "linalg": CONTENT_LINALG}


def _pdf_escape(data: bytes) -> bytes:
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class PdfWriter:
    def __init__(self):
        self.objects: list[bytes] = []

    def add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects)  # 1-based

    def reserve(self) -> int:
        self.objects.append(b"")
        return len(self.objects)

    def set(self, num: int, body: bytes):
        self.objects[num - 1] = body

    def build(self, root: int) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n" % (len(self.objects) + 1)
        out += b"0000000000 65535 f \n"
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(self.objects) + 1,
            root,
            xref,
        )
        return bytes(out)


def build_pdf(content=None) -> bytes:
    content = content or CONTENT
    w = PdfWriter()
    catalog = w.reserve()
    pages_obj = w.reserve()

    page_refs = []
    for lines in content:
        chars = []
        for line in lines:
            for ch in line:
                if ch not in chars:
                    chars.append(ch)
        # split into fonts of at most 200 glyphs
        chunks = [chars[i : i + 200] for i in range(0, len(chars), 200)] or [[]]
        font_objs = []
        for chunk in chunks:
            code_of = {ch: idx + 1 for idx, ch in enumerate(chunk)}
            charprocs = []
            for ch in chunk:
                proc = b"1000 0 d0\n"
                charprocs.append(w.add(b"<< /Length %d >>\nstream\n" % len(proc) + proc + b"\nendstream"))
            names = b" ".join(b"/g%d" % (i + 1) for i in range(len(chunk)))
            diffs = b"[" + names + b"]"
            encoding = b"<< /Type /Encoding /Differences [1 " + names + b"] >>"
            to_unicode = _cmap(chunk)
            tu_obj = w.add(b"<< /Length %d >>\nstream\n" % len(to_unicode) + to_unicode + b"\nendstream")
            font = (
                b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
                b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << "
                + b" ".join(b"/g%d %d 0 R" % (i + 1, obj) for i, obj in enumerate(charprocs))
                + b" >> /Encoding "
                + encoding
                + b" /FirstChar 1 /LastChar %d /Widths [" % max(1, len(chunk))
                + b" ".join(b"1000" for _ in chunk)
                + b"] /Resources << >> /ToUnicode %d 0 R >>" % tu_obj
            )
            font_objs.append((w.add(font), code_of))

        # content stream
        ops = [b"BT", b"/F1 11 Tf", b"14 TL"]
        y = 760
        for line in lines:
            ops.append(b"1 0 0 1 48 %d Tm" % y)
            y -= 20
            run_font = None
            run = b""
            for ch in line:
                for fi, (fobj, code_of) in enumerate(font_objs):
                    if ch in code_of:
                        if run_font != fi:
                            if run:
                                ops.append(b"(" + _pdf_escape(run) + b") Tj")
                                run = b""
                            ops.append(b"/F%d 12 Tf" % (fi + 1))
                            run_font = fi
                        run += bytes([code_of[ch]])
                        break
            if run:
                ops.append(b"(" + _pdf_escape(run) + b") Tj")
        ops.append(b"ET")
        content = b"\n".join(ops)
        c_obj = w.add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

        font_res = b" ".join(b"/F%d %d 0 R" % (i + 1, f[0]) for i, f in enumerate(font_objs))
        page = w.add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << %s >> >> /Contents %d 0 R >>"
            % (pages_obj, font_res, c_obj)
        )
        page_refs.append(page)

    w.set(catalog, b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    w.set(
        pages_obj,
        b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in page_refs)
        + b"] /Count %d >>" % len(page_refs),
    )
    return w.build(catalog)


def _cmap(chars) -> bytes:
    head = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
"""
    body = b"%d beginbfchar\n" % len(chars)
    for idx, ch in enumerate(chars):
        dst = ch.encode("utf-16-be").hex().upper()
        body += b"<%02X> <%s>\n" % (idx + 1, dst.encode("ascii"))
    body += b"endbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    return head + body


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    which = "calculus"
    for a in sys.argv[1:]:
        if a.startswith("--set="):
            which = a.split("=", 1)[1]
    default_name = "示例讲义.pdf" if which == "calculus" else "线性代数示例.pdf"
    out = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", default_name
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    content = SETS[which]
    data = build_pdf(content)
    with open(out, "wb") as fh:
        fh.write(data)
    print("wrote %s (%d bytes, %d pages)" % (out, len(data), len(content)))


if __name__ == "__main__":
    main()
