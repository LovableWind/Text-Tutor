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
    """顶层只放一个启动器；程序本体都在 _internal\\ 里。"""
    internal = os.path.join(dst, "_internal")
    os.makedirs(internal, exist_ok=True)

    # 顶层是编译好的 旁批.exe（带图标、不弹黑窗）；.bat 退到 _internal 当备用入口
    exe_src = os.path.join(ROOT, "tools", "bin", "Pangpi.exe")
    if os.path.exists(exe_src):
        shutil.copy2(exe_src, os.path.join(dst, "旁批.exe"))

    bat = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0\.."

if not exist "%ROOT%\_internal\runtime\pythonw.exe" (
  echo.
  echo   找不到程序文件：_internal\runtime\pythonw.exe
  echo.
  pause
  exit /b 1
)

if not exist "%ROOT%\data" mkdir "%ROOT%\data"
if not exist "%ROOT%\data\.unblocked" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%ROOT%' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
  echo ok> "%ROOT%\data\.unblocked"
)

start "" "%ROOT%\_internal\runtime\pythonw.exe" "%ROOT%\_internal\app\server.py" --data-dir "%ROOT%\data" >> "%ROOT%\data\app.log" 2>&1
"""
    with open(os.path.join(internal, "旁批（备用启动）.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(bat)

    dbg = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
  "runtime\python.exe" "app\server.py" --data-dir "%~dp0..\data" %*
) else (
  python "app\server.py" --data-dir "%~dp0..\data" %*
)
echo.
echo 服务已退出。
pause
"""
    with open(os.path.join(internal, "调试启动.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(dbg)

    quit_bat = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%~dp0..\data\server.json'; if (Test-Path $p) { $j=Get-Content $p -Raw | ConvertFrom-Json; Stop-Process -Id $j.pid -Force -ErrorAction SilentlyContinue; Write-Host '已退出旁批' } else { Write-Host '旁批没有在运行' }"
timeout /t 2 >nul
"""
    with open(os.path.join(internal, "退出旁批.bat"), "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(quit_bat)


def build(zip_it=True, runtime_src=None):
    runtime_src = runtime_src or os.path.dirname(os.path.realpath(sys.executable))
    out = os.path.join(DIST, NAME)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)

    internal = os.path.join(out, "_internal")
    os.makedirs(internal, exist_ok=True)

    copytree(os.path.join(ROOT, "app"), os.path.join(internal, "app"),
             ignore=lambda d, names: {n for n in names if n in ("__pycache__", ".pytest_cache")})
    copytree(os.path.join(ROOT, "web"), os.path.join(internal, "web"),
             ignore=lambda d, names: {n for n in names if n == "tests"})
    copytree(os.path.join(ROOT, "samples"), os.path.join(internal, "samples"), ignore=None)
    # 顶层只留三样：启动器、使用说明、_internal；其余文档收进 _internal
    guide = os.path.join(ROOT, "使用说明.md")
    if os.path.exists(guide):
        shutil.copy2(guide, os.path.join(out, "使用说明.md"))
    for doc in ("README.md", "LICENSE", "CHANGELOG.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(internal, doc))

    print("copying runtime from", runtime_src)
    size = trim_runtime(runtime_src, os.path.join(internal, "runtime"))
    print("runtime trimmed to", human(size))
    lic = os.path.join(runtime_src, "LICENSE.txt")
    if os.path.exists(lic):
        shutil.copy2(lic, os.path.join(internal, "runtime", "PYTHON-LICENSE.txt"))

    write_launchers(out)

    total = 0
    for root, _d, files in os.walk(out):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print("bundle size:", human(total))

    # smoke test the bundled interpreter
    py = os.path.join(internal, "runtime", "python.exe")
    if os.path.exists(py):
        proc = subprocess.run(
            [py, "-c", "import json,ctypes,http.server,urllib.request,zlib;print('runtime ok')"],
            capture_output=True, text=True,
        )
        print("smoke:", (proc.stdout or proc.stderr).strip()[:300])

    # 打包完顺手清掉源码树里的字节码缓存：网页上传不认 .gitignore，
    # 这些 .pyc 会被当成普通文件拖进仓库。
    cleaned = 0
    for root, dirs, _files in os.walk(ROOT):
        if "dist" in root.split(os.sep):
            continue
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)
                cleaned += 1
    if cleaned:
        print("cleaned %d __pycache__ dirs" % cleaned)

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
