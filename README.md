# 旁批 · 讲义伴读（Margin Tutor）

## 下载

Windows 便携版：[Releases](https://github.com/LovableWind/Text-Tutor/releases/latest) → 下载 `Pangpi-v1.0.0-portable-win64.zip`，解压后双击「启动旁批.bat」。

首次使用请先在右上角 ⚙ 里填入自己的 DeepSeek API Key。

---

选中讲义中的任意一句话，在侧边窄窗里得到一段**贴着讲义**的讲解：只用讲义前面已经讲过的内容；需要超前时标注后文章节；讲义没有的东西必须显式标为「补充」。选中习题时只给分层提示。

面向 Windows，零安装：便携包里带了一份裁剪过的 CPython 运行时，双击即用。

```
┌───────────── 你的 PDF 阅读器 ─────────────┐   ┌──── 旁批（置顶窄窗）──────────┐
│  选中一句话 → Ctrl+C                      │   │ P.12 · 3.2 单调有界准则       │
│  或 Ctrl+Alt+D 取词                       │──▶│ 原文「……」                    │
│  或 Win+Shift+S 截图公式                  │   │ 定位 / 讲解 / 依据 / 易错点    │
└───────────────────────────────────────────┘   │ ⏭ 引申  ➕ 补充               │
                                                │ [给提示] [追问] [复制]         │
                                                └───────────────────────────────┘
```

## 组成

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| 本地服务 | `app/server.py` | HTTP/SSE、会话状态、卡片持久化、静态资源 |
| 取词 | `app/win32.py` | 剪贴板读写（文本/DIB→PNG）、全局热键、`Ctrl+C` 注入、置顶、拉起浏览器 |
| 讲义索引 | `app/pdftext.py` | 纯 Python PDF 解析（xref、对象流、Flate、Type0/Type3、ToUnicode） |
| | `app/handout.py` | 分页文本、质量判定、目录识别、定位（精确→3-gram）、已讲要点 |
| 模型接入 | `app/llm.py` | Anthropic Messages / OpenAI 兼容双协议流式，图片输入，思考开关 |
| 边界自查 | `app/guard.py` | 抓正文里越界的页码/小节号，触发一次"只改引用"的重写 |
| 提示词 | `app/prompts.py` | 讲义边界、三类标注规则、提示阶梯、追问上下文 |
| 界面 | `web/index.html` `styles.css` `app.js` | 卡片流、讲义面板、设置、SSE 客户端 |
| 渲染 | `web/math.js` `md.js` | 无依赖的 TeX 子集渲染（含 `\big` 家族、分数、根式、大型运算符、cases/matrix） + 安全 Markdown 渲染（含 XSS 防护） |
| 打包 | `tools/build_portable.py` | 裁剪运行时、写启动器、打 zip |

数据目录（便携模式在程序目录下，否则 `%APPDATA%\Pangpi`）：

```
data/
  settings.json   设置（含 API Key，明文，仅本机）
  handout.json    讲义索引：每页文本 + 目录 + 质量
  handout.pdf     原始讲义副本
  cards.json      最近的卡片历史
  img/*.png       截图
  token           本地 API 令牌
  browser/        Edge/Chrome 的独立 profile（窗口用）
```

## 从源码运行

```powershell
python app\server.py                 # 打开窄窗
python app\server.py --no-window     # 只起服务，浏览器手动开 http://127.0.0.1:<port>/?t=<token>
```

需要 Python 3.10+，只用标准库。`--no-hotkey` 可跳过全局热键（远程桌面/测试时用），`--keep-alive` 关闭"窗口关掉就退出"的心跳看门狗。

## HTTP 接口

所有 `/api/*` 需要请求头 `X-Pangpi-Token`（或 `?t=`），令牌写在 `data/token`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 设置（脱敏）、讲义摘要、当前页、最近卡片 |
| POST | `/api/settings` | 局部更新设置 |
| POST | `/api/handout` | 原始 PDF 字节 + `X-Filename`，后台建索引 |
| GET | `/api/handout/status` | `{state, progress, message}` |
| POST | `/api/page` | 设置当前页，返回所在小节 |
| POST | `/api/locate` | 文本 → 页码（精确命中或 3-gram 相似度） |
| POST | `/api/explain` | **SSE**：`meta` → `delta`×n / `thinking` → `done` / `error` |
| POST | `/api/chat` | **SSE**：追问，同上 |
| GET | `/api/events` | **SSE**：`capture`（取词）、`handout`（索引进度） |
| POST | `/api/test` | 连通性测试 |
| POST | `/api/pin` / `/api/reopen` / `/api/capture` / `/api/card/delete` | 窗口与卡片操作 |

## 讲义约束是怎么做出来的

1. **页码定位**：取到的文字在讲义索引里精确匹配；匹配不到就用字符 3-gram 覆盖率打分，低于阈值时不猜页码范围。
2. **知识边界**：`第 1 页—第 N-1 页` 的"关键结论清单"（定义/定理/引理/例题等行）+ 上一页原文 + 当前页原文，一起放进系统提示。
3. **三档引用规则**（写死在系统提示里）：
   - 已讲范围内：正常推导，并在「依据」里注明页码/定理号
   - 后面才讲：`⏭ 引申 · 第X节《标题》（第Y页）：一句话`，**不许展开证明**
   - 讲义没有：`➕ 补充：`，先讲清楚是什么、为什么，再说怎么用
4. **防编造**：明确禁止编造讲义里没有的编号和页码；记不清就只描述内容。
5. **提示阶梯**：`hint_level` 1→3，分别对应"只给方向""给关键一步""给接近完整的路线"，三层之后才开放完整解答。
6. **边界自查**：答案生成后，`guard.check_scope()` 机械地检查"正文里有没有当前页之后的页码/小节号"。命中就再发一次"只改引用、别动内容"的重写请求；重写稿必须通过同样的检查、且长度不低于原稿 60% 才替换，否则保留原稿并提示。

实测（`deepseek-flash`，两类讲义共 17 个用例 × 多轮）：

| 场景 | 自查前 | 自查后 |
| --- | --- | --- |
| 数学分析样例（11 例） | 9～11 / 11 | 11 / 11 |
| 线性代数样例（6 例，换讲义） | 4 / 6 | 6 / 6 |

"自查前"的失败几乎都是同一类：推导本身没错，但正文顺手写了"第 3 页会用导数解释"——页码是对的，位置不对，规则要求它必须待在 ⏭ 行里。

## 测试

```powershell
python tests\e2e.py            # 31 项端到端断言（本地假模型，不需要真 Key）
python tests\test_scope.py     # 22 项离线边界断言：后页正文一个字都不进提示词
python tests\audit_grounding.py  # 真模型 11 例：越界引用 / 编造编号 / 标注缺失
python tests\audit_transfer.py   # 换一份线性代数讲义再测 6 例（防过拟合）
python tests\smoke_dist.py     # 便携包自检（用包内 runtime 起服务）
python tools\live_check.py     # 真实接口质量抽查：$env:DSK 提供 Key
python tools\live_e2e.py "选中的句子" 2   # 走完整服务链路打真模型
node web\tests\test_math.mjs   # 数学渲染 143 项断言 / 34 组
node web\tests\test_md.mjs     # Markdown 渲染 123 项断言 / 34 组
```

`audit_*` 里的 `NO_REPAIR=1` 可以关掉自查修正，用来对比"裸模型"和"自查后"的差别。

`tools/make_sample_pdf.py` 生成 4 页中文数学讲义（Type3 + ToUnicode，几十 KB），既是测试夹具也是随包示例。

## 打包

```powershell
python tools\build_portable.py                 # 用当前解释器作运行时
python tools\build_portable.py --runtime "C:\Python312" --no-zip
```

产物：`dist\旁批\`（约 30 MB）与 `dist\旁批-便携版-YYYYMMDD.zip`（约 10 MB）。运行时只保留 `Lib` 标准库与必要 DLL，删掉 `site-packages`、`tkinter`、`tcl`、`idlelib` 等。

## 已知限制

- 只支持 Windows（剪贴板/热键/置顶依赖 Win32；其它平台服务能起，取词需手动粘贴）。
- PDF 文字层是矢量笔画（手写板导出）或扫描件时，无法自动建页码索引，需要手动指定当前页。
- 公式渲染是 TeX 子集，极复杂的排版会退化成源码文本。
- 回答正确性由模型负责；提示词保证的是"引用边界"，不是"数学无误"。
- 单实例：同一数据目录只跑一个服务，重复启动会聚焦已有窗口。

## License

MIT（`LICENSE`）。便携包内的 CPython 运行时遵循 PSF 许可证，见 `runtime/PYTHON-LICENSE.txt`。
