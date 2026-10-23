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

CONTENT_HUM = [
    [
        "第一章 先秦儒家",
        "1.1 孔子的仁学",
        "孔子认为，「仁」是礼的内在依据，礼是仁的外在表现。",
        "概念：仁者爱人；己所不欲，勿施于人。",
        "例 1.1 《论语》中樊迟问仁，子曰：爱人。",
        "影响：孟子由此发展出性善论，荀子则转向隆礼重法。",
    ],
    [
        "1.2 孟子的性善论",
        "孟子主张人性本善，以四端立论：恻隐、羞恶、辞让、是非。",
        "例 1.2 孺子入井：人皆有怵惕恻隐之心，非为交情、非求名誉。",
        "论证结构：先立事实，再推出四端，最后归于扩充。",
        "评价：性善论为教化提供了根据，但弱化了制度约束。",
    ],
    [
        "第二章 古希腊哲学",
        "2.1 柏拉图的理念论",
        "柏拉图认为，可感事物分有理念，理念才是真正的存在。",
        "例 2.1 洞穴喻：囚徒只见影子，出洞者才见真实。",
        "意义：把知识的对象与意见的对象区分开来。",
        "背景：回应智者派的相对主义。",
    ],
    [
        "2.2 亚里士多德的形式质料说",
        "亚里士多德提出四因说，以形式与质料解释生成。",
        "主张：形式内在于个别事物，不脱离事物而存在。",
        "习题 2.1 试比较柏拉图与亚里士多德对「形式」的理解。",
        "论述题：结合文本，谈谈理念论对后世科学的影响。",
    ],
]

CONTENT_DEMO = [
    [
        "第一章 数列与极限",
        "1.1 数列极限的定义",
        "定义 1.1 设 {a_n} 是一个数列，A 是一个常数。若对任意 ε>0，存在正整数 N，使得当 n>N 时恒有 |a_n - A| < ε，则称数列 {a_n} 收敛于 A。",
        "例 1.1 用定义证明 lim (n+1)/n = 1。",
        "证明 对任意 ε>0，取 N = [1/ε]+1，当 n>N 时，|(n+1)/n - 1| = 1/n < ε。",
        "注意 这里的 N 依赖 ε；ε 越小，N 通常越大。",
    ],
    [
        "1.2 收敛数列的性质",
        "定理 1.1（唯一性）收敛数列的极限唯一。",
        "定理 1.2（有界性）收敛数列必有界。",
        "定理 1.3（保号性）若 lim a_n = A > 0，则存在 N，当 n>N 时 a_n > 0。",
        "例 1.2 若 lim a_n = 2，证明存在 N，当 n>N 时 a_n > 1。",
        "证明 取 ε = 1，由定义 1.1 得存在 N，使 |a_n - 2| < 1，即 a_n > 1。",
    ],
    [
        "1.3 单调有界准则",
        "定理 1.4 单调有界数列必有极限。",
        "证明思路 以单调递增且有上界为例，取所有上界中最小的那个，记为 A。",
        "第一步 验证 A 是上界：对一切 n，都有 a_n ≤ A。",
        "第二步 验证 A 是极限：对任意 ε>0，都存在某一项 a_N > A - ε。",
        "这两步合起来就得到 |a_n - A| < ε。",
        "例 1.3 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛。",
    ],
    [
        "1.4 实数的确界原理",
        "定义 1.2 若数集 S 有上界，且所有上界中存在最小的一个，则称它为 S 的上确界，记作 sup S。",
        "定理 1.5（确界原理）非空有上界的实数集必有上确界。",
        "注 1.3 节里「所有上界中最小的那个」指的就是上确界；确界原理保证了它一定存在。",
        "例 1.4 数集 {1 - 1/n} 的上确界是 1，但它取不到。",
    ],
    [
        "第二章 导数与微分",
        "2.1 导数的定义",
        "定义 2.1 设函数 y=f(x) 在点 x_0 的某邻域内有定义，若极限 lim [f(x_0+Δx) - f(x_0)]/Δx (Δx→0) 存在，则称 f 在 x_0 处可导。",
        "定理 2.1 可导必连续，连续不一定可导。",
        "例 2.1 求 f(x)=x^2 在 x=1 处的导数。",
    ],
    [
        "2.2 求导法则与高阶导数",
        "公式 (uv)' = u'v + uv'，(u/v)' = (u'v - uv')/v^2。",
        "定义 2.2 二阶导数记作 f''(x) 或 d^2y/dx^2。",
        "定理 2.2（莱布尼茨公式）(uv)^(n) = sum C(n,k) u^(k) v^(n-k)。",
        "例 2.2 求 y = x e^x 的二阶导数。",
    ],
    [
        "习题",
        "习题 1.1 用定义证明 lim (2n+1)/(n+3) = 2。",
        "习题 1.2 设 a_1 = 1，a_{n+1} = sqrt(2 + a_n)，证明 {a_n} 收敛并求其极限。",
        "习题 2.1 设 f(x) = x^3 - 3x，讨论 f 在 [-2,2] 上的单调性与极值。",
    ],
]

SETS = {"calculus": CONTENT, "linalg": CONTENT_LINALG, "humanities": CONTENT_HUM,
        "demo": CONTENT_DEMO}


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
    default_name = {"calculus": "示例讲义.pdf", "linalg": "线性代数示例.pdf",
                    "humanities": "人文示例.pdf",
                    "demo": "演示讲义.pdf"}.get(which, "示例讲义.pdf")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if which == "demo":
        out = args[0] if args else os.path.join(root, "demo", "演示讲义.pdf")
    else:
        out = args[0] if args else os.path.join(root, "samples", default_name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    content = SETS[which]
    data = build_pdf(content)
    with open(out, "wb") as fh:
        fh.write(data)
    print("wrote %s (%d bytes, %d pages)" % (out, len(data), len(content)))


if __name__ == "__main__":
    main()
