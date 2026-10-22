# -*- coding: utf-8 -*-
"""Static wiring check: every $("#id") in app.js must exist in index.html."""
import re
import sys
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
js = open(os.path.join(root, "web", "app.js"), encoding="utf-8").read()
ids = set(re.findall(r'id="([^"]+)"', html))
used = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', js))
used |= set(re.findall(r'on\("#([A-Za-z0-9_-]+)"', js))
missing = sorted(used - ids)
dupes = sorted(i for i in ids if html.count('id="%s"' % i) > 1)
meta = re.search(r'<meta name="pangbi-ui" content="([^"]+)"', html)
js_ver = re.search(r'UI_VERSION = "([^"]+)"', js)
same = bool(meta and js_ver and meta.group(1) == js_ver.group(1))
print("ui version:", (meta.group(1) if meta else "missing"), "/", (js_ver.group(1) if js_ver else "missing"), "match:", same)
if not same:
    missing.append("UI 版本号不一致")

print("ids:", len(ids), "used:", len(used))
print("missing:", missing)
print("duplicate ids:", dupes)
sys.exit(1 if missing or dupes else 0)
