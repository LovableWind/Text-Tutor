# -*- coding: utf-8 -*-
"""macOS 后端测试：接口齐全、退化行为正确、打包带执行位。"""

from __future__ import annotations

import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import macos  # noqa: E402

passed, failed = 0, []


def check(name, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print("  ok   " + name)
    else:
        failed.append(name)
        print("  FAIL " + name + " " + str(detail))


def main():
    # 接口齐全
    for name in ("clipboard_sequence", "read_clipboard", "write_clipboard_text",
                 "send_copy", "grab_selection", "has_window", "pin_topmost",
                 "focus_window", "open_app_window", "screen_size", "find_browser",
                 "HotkeyListener", "parse_hotkey"):
        check("has " + name, hasattr(macos, name))

    check("hotkey unsupported", macos.parse_hotkey("Ctrl+Alt+D") == (0, None))
    check("hotkey listener returns False",
          macos.HotkeyListener().start("Ctrl+Alt+D", lambda: None) is False)
    check("pin_topmost degrades", macos.pin_topmost("x", True) is False)
    check("has_window without profile", macos.has_window() is False)
    check("tiff helper tolerant", macos._tiff_to_png(b"") == b"")
    w, h = macos.screen_size()
    check("screen_size sane", isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0, (w, h))
    check("read_clipboard returns tuple", isinstance(macos.read_clipboard(), tuple))

    # server 的平台分支
    server_src = open(os.path.join(ROOT, "app", "server.py"), encoding="utf-8").read()
    check("server switches backend", 'sys.platform == "darwin"' in server_src
          and "import macos as win32" in server_src)

    # 打包：.command 必须带执行位，否则 macOS 双击跑不起来
    import build_portable
    out = build_portable.build_mac(zip_it=False)
    command = os.path.join(out, "旁批.command")
    check("command exists", os.path.exists(command))
    body = open(command, encoding="utf-8").read()
    check("command is a shell script", body.startswith("#!/bin/bash"))
    check("command runs server", "_internal/app/server.py" in body)
    check("no runtime bundled", not os.path.exists(os.path.join(out, "_internal", "runtime")))

    zpath = os.path.join(ROOT, "dist", "_test_mac.zip")
    build_portable.make_zip(out, zpath, executables={"旁批.command"})
    with zipfile.ZipFile(zpath) as zf:
        info = zf.getinfo("旁批.command")
        mode = (info.external_attr >> 16) & 0o777
        check("zip exec bit", mode == 0o755, oct(mode))
        check("zip marked unix", info.create_system == 3, info.create_system)
        check("zip has app", any(n.startswith("_internal/app/") for n in zf.namelist()))
    os.remove(zpath)

    print("\n%d passed, %d failed" % (passed, len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
