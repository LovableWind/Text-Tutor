# -*- coding: utf-8 -*-
"""Build a portable Windows folder (and a zip) that runs without installing Python.

    python tools/build_portable.py [--runtime <python dir>] [--no-zip]

The bundle contains the app, the web assets, the sample handout, a launcher and
a trimmed copy of the CPython runtime this script runs under.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
NAME = "旁批"

DROP_DIRS = [
    "site-packages", "test", "tests", "idlelib", "ensurepip", "tkinter",
    "turtledemo", "lib2to3", "pydoc_data", "__pycache__", "venv",
    "distutils", "config-3.12-winx64",
]
DROP_DLLS = ["_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "tcl90t.dll", "tk90t.dll", "sqlite3.dll"]


def human(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024)


def copytree(src: str, dst: str, ignore=None):
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def trim_runtime(src: str, dst: str) -> int:
    def ignore(dirname, names):
        base = os.path.basename(dirname)
        skip = []
        if base == "Lib":
            skip = [n for n in names if n in DROP_DIRS]
        if base == "DLLs":
            skip = [n for n in names if n in DROP_DLLS]
        return set(skip)

    copytree(src, dst, ignore=ignore)
    for junk in ("include", "libs", "Scripts", "tcl", "Doc", "share"):
        shutil.rmtree(os.path.join(dst, junk), ignore_errors=True)
    for root, dirs, _files in os.walk(dst):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)
    total = 0
    for root, _dirs, files in os.walk(dst):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def write_launchers(dst: str):
    bat = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "runtime\pythonw.exe" (
  echo 找不到内置运行时：runtime\pythonw.exe
  echo 请重新解压完整压缩包，或安装 Python 3.10+ 后双击「调试启动.bat」。
  pause
  exit /b 1
)
if not exist "data" mkdir "data"
start "" "runtime\pythonw.exe" "app\server.py" >> "data\app.log" 2>&1
"""
    with open(os.path.join(dst, "启动旁批.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(bat)

    dbg = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  "runtime\python.exe" "app\server.py" %*
) else (
  python "app\server.py" %*
)
echo.
echo 服务已退出。
pause
"""
    with open(os.path.join(dst, "调试启动.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(dbg)

    unblock_bat = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 正在解除 Windows 对下载文件的锁定（只影响本文件夹，不改系统设置）...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue"
echo.
echo 完成。以后双击「启动旁批.bat」不会再弹「此文件可能有害」。
timeout /t 3 >nul
"""
    with open(os.path.join(dst, "解除锁定.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(unblock_bat)

    quit_bat = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%~dp0data\server.json'; if (Test-Path $p) { $j=Get-Content $p -Raw | ConvertFrom-Json; Stop-Process -Id $j.pid -Force -ErrorAction SilentlyContinue; Write-Host '已退出旁批' } else { Write-Host '旁批没有在运行' }"
timeout /t 2 >nul
"""
    with open(os.path.join(dst, "退出旁批.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(quit_bat)


def build(zip_it=True, runtime_src=None):
    runtime_src = runtime_src or os.path.dirname(os.path.realpath(sys.executable))
    out = os.path.join(DIST, NAME)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)

    copytree(os.path.join(ROOT, "app"), os.path.join(out, "app"),
             ignore=lambda d, names: {n for n in names if n in ("__pycache__", ".pytest_cache")})
    copytree(os.path.join(ROOT, "web"), os.path.join(out, "web"),
             ignore=lambda d, names: {n for n in names if n == "tests"})
    copytree(os.path.join(ROOT, "samples"), os.path.join(out, "samples"), ignore=None)
    for doc in ("README.md", "使用说明.md", "LICENSE"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, doc))

    print("copying runtime from", runtime_src)
    size = trim_runtime(runtime_src, os.path.join(out, "runtime"))
    print("runtime trimmed to", human(size))
    lic = os.path.join(runtime_src, "LICENSE.txt")
    if os.path.exists(lic):
        shutil.copy2(lic, os.path.join(out, "runtime", "PYTHON-LICENSE.txt"))

    write_launchers(out)

    total = 0
    for root, _d, files in os.walk(out):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print("bundle size:", human(total))

    # smoke test the bundled interpreter
    py = os.path.join(out, "runtime", "python.exe")
    if os.path.exists(py):
        proc = subprocess.run(
            [py, "-c", "import json,ctypes,http.server,urllib.request,zlib;print('runtime ok')"],
            capture_output=True, text=True,
        )
        print("smoke:", (proc.stdout or proc.stderr).strip()[:300])

    if zip_it:
        stamp = time.strftime("%Y%m%d")
        zpath = os.path.join(DIST, "%s-便携版-%s.zip" % (NAME, stamp))
        if os.path.exists(zpath):
            os.remove(zpath)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, _d, files in os.walk(out):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, DIST)
                    zf.write(full, rel)
        print("zip:", zpath, human(os.path.getsize(zpath)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default=None, help="source python distribution directory")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()
    build(zip_it=not args.no_zip, runtime_src=args.runtime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
