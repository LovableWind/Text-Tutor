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
missing = sorted(used - ids)
dupes = sorted(i for i in ids if html.count('id="%s"' % i) > 1)
print("ids:", len(ids), "used:", len(used))
print("missing:", missing)
print("duplicate ids:", dupes)
sys.exit(1 if missing or dupes else 0)
